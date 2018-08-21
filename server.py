#!/opt/bin/python3
# -*- coding: utf-8 -*-
"""
Very simple HTTP server in python to control Android tablet through ADB
Usage::
    ./server.py [<port>]
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import logging
import subprocess
import re
import os
import socket
import time
import json
import hashlib
import struct

from urllib.parse import quote_plus
from urllib.request import urlopen
from socketserver import ThreadingMixIn
from threading import Thread

def nameForCompare(st):
    return st["cat"].lower() + st["name"].lower()\
        .replace("_", " ")\
        .replace("-", " ")\
        .replace("vk.com/iptv_iptv", "")\
        .replace("(vk.com/iptv_iptv)", "")\
        .replace("TV", "")\
        .replace(" ", "")\
        .strip()

def timeToSleepNever():
    return time.time() + 100*365*24*60*60  

def reportText(text):
    def open_website(url):
        return urlopen(url)


    Thread(target=open_website, args=["http://192.168.121.75/show?text="+quote_plus(text)]).start()

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

    loadedChannelsAt = 0
    youtubeChannel = 0
    youtubeChannels = []
    youtubeChannelsByIds = {}

    sleepAt = timeToSleepNever() # Sleep tablet at that time

    def __init__(self, *args):
        HTTPServer.__init__(self, *args)
        self.loadM3U()

    def adbShellCommand(self, command):
        resultStr = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read()
        if len(resultStr) > 0:
            subprocess.Popen("adb connect 192.168.121.166:5556", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()
            # And try again
            subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()

    def loadM3UIfNeeded(self):
        if len(self.youtubeChannels) == 0 or (time.time() - self.loadedChannelsAt) > 3600:
            # logging.info("Last load at " + str(time.time() - self.loadedChannelsAt))
            # we load channels each hour or on start
            self.loadM3U()

    def loadM3U(self):
        try:
            logging.info("LOADING CHANNELS\n")

            '''
            response = urlopen("http://iptviptv.do.am/_ld/0/1_IPTV.m3u")
            # response = urlopen("http://getsapp.ru/IPTV/Auto_IPTV.m3u")
            html = response.read().decode("utf-8")
            name = ""
            url = ""

            self.youtubeChannels = []
            for line in html.splitlines():
                if line.startswith("#EXTINF"):
                    name = re.search('#EXTINF:-?\d*\,(.*)', line).group(1).strip()
                elif line.startswith("http"):
                    url = line
                    lowName = name.strip().lower()
                    if not "erotic" in lowName\
                        and not "xxx" in lowName\
                        and not "olala" in lowName\
                        and not "o-la-la" in lowName\
                        and not "erox tv" in lowName\
                        and not "playboy" in lowName:
                    self.youtubeChannels.append({ "name": name, "url": url })
                    name = ""
            '''

            response = urlopen("http://acetv.org/js/data.json?0.26020398076972606").read().decode("utf-8")
            # logging.info(response)
            channels = json.loads(response)
            
            self.youtubeChannels = []

            for ch in channels["channels"]:
                self.youtubeChannels.append({ "name": ch["name"], "url": "http://192.168.121.38:8000/pid/" + ch["url"] + "/stream.mp4", "cat": ch["cat"] })

            self.youtubeChannels.sort(key=lambda r:nameForCompare(r))
            for ch in self.youtubeChannels:
                urlHash = bytes(hashlib.sha256(ch["url"].encode('utf-8')).digest())
                #logging.info(str(urlHash))
                ch["id"] = struct.unpack("<I", urlHash[0:4])[0] % 1000000
                if ch["id"] in self.youtubeChannelsByIds and self.youtubeChannelsByIds[ch["id"]]["url"] != ch["url"]:
                    logging.error("HASH CLASH: " + str(ch["id"]) + " " + ch["url"] + " " + self.youtubeChannelsByIds[ch["id"]]["url"]) 
                else:
                    self.youtubeChannelsByIds[ch["id"]] = ch

            with open(os.path.dirname(os.path.abspath(__file__)) + "channels.json", "w") as write_file:
                json.dumps(self.youtubeChannels, write_file)

            self.loadedChannelsAt = time.time()
            logging.info("LOADED CHANNELS")
        except Exception as e:
            logging.info("FAILED TO LOAD CHANNELS:" + str(e))

class HomeHTTPHandler(BaseHTTPRequestHandler):
    def writeResult(self, res):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\"}").encode('utf-8'))

    def adbShellCommand(self, command):
        self.server.adbShellCommand(command)

    def stopCurrent(self):
        self.adbShellCommand("am force-stop org.videolan.vlc")

    def playCurrent(self):
        self.stopCurrent()
        logging.info(self.server.youtubeChannelsByIds[self.server.youtubeChannel]["url"])
        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -d \"" + 
                self.server.youtubeChannelsByIds[self.server.youtubeChannel]["url"] + 
                "\"")

    def milightCommand(self, cmd):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
        sock.sendto(cmd, ("192.168.121.35", 8899))
 
    def do_GET(self):
        logging.info("GET request,\nPath: %s", str(self.path))
        pathList = list(filter(None, self.path.split("/")))
        
        if len(pathList) == 0:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            htmlContent = ""
            with open(os.path.dirname(os.path.abspath(__file__)) + '/web/index.html', 'r') as myfile:
                htmlContent = myfile.read()

            strr = ""
            
            currName = None
            btns = ""

            cats = set()

            for ytb in self.server.youtubeChannels:
                cats.add(ytb["cat"])
                if currName != None and nameForCompare(currName) != nameForCompare(ytb):
                    strr += "<div class='channel-line' data-cat='" + currName["cat"] + "'>" + currName["name"] + "&nbsp;" + btns + "</div>" + "\n"
                    btns = ""
                btns += "<button class='action' data-url='/tablet/play/" \
                    + str(ytb["id"]) + "'  data-uri='"\
                    + ytb["url"] + "' data-name='" + ytb["name"] + "'> "\
                    + str(ytb["id"]) +" </button>" + "\n"
                currName = ytb

            if len(btns) > 0:
                strr += "<div class='channel-line'>" + currName["name"] + "&nbsp;" + btns + "</div>" + "\n"

            # Categories
            htmlContent = htmlContent.replace("<!--{{{categories}}}-->",\
                " ".join(sorted(map(lambda c : "\t<option value='" + c + "'>" + c + "</option>\n", cats))))
            # Channels
            htmlContent = htmlContent.replace("<!--{{{channels}}}-->", strr)

            self.wfile.write(htmlContent.encode('utf-8'))
        elif pathList == list(["favicon.ico"]):
            self.send_response(200)
            self.send_header('Content-type', 'image/x-ico')
            self.end_headers()

            with open(os.path.dirname(os.path.abspath(__file__)) + '/web/favicon.ico', 'rb') as myfile:
                self.wfile.write(myfile.read())
        else:
            self.writeResult("UNKNOWN CMD {}".format(self.path))

    def do_POST(self):
        pathList = list(filter(None, self.path.split("/")))
        if pathList[0] == "init":
            self.send_response(200)
        elif pathList[0] == "tablet" and pathList[1] == "play":
            if (len(pathList) > 2):
                self.server.youtubeChannel = int(pathList[2])
                ytb = self.server.youtubeChannelsByIds[self.server.youtubeChannel]
                reportText("Включаем " + ytb["name"])
                
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "stop"]):
            self.stopCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "playagain"]):
            self.stopCurrent()
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "volup"]):
            reportText("Громче")
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_UP")
            self.writeResult("OK")
        elif pathList == list(["tablet", "voldown"]):
            reportText("Тише")
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_DOWN")
            self.writeResult("OK")
        elif pathList == list(["tablet", "onoff"]):
            self.adbShellCommand("input keyevent KEYCODE_POWER")
            self.writeResult("OK")
        elif pathList == list(["tablet", "russia24"]):
            self.adbShellCommand("am start -a android.intent.action.VIEW -d \"http://www.youtube.com/watch?v=K59KKnIbIaM\" --ez force_fullscreen true")
            self.writeResult("OK")
        elif pathList == list(["tablet", "reboot"]):
            self.adbShellCommand("reboot")
            self.writeResult("OK")
        elif pathList == list(["self", "reboot"]):
            subprocess.Popen("reboot", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read() # Reboot self
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "sleepin":
            self.server.sleepAt = time.time() + int(pathList[2])

            minsToSwitchOff = int((self.server.sleepAt - time.time())/60)
            secsToSwitchOff = int((self.server.sleepAt - time.time())%60)
            reportText("Телевизор выключится через " + str(minsToSwitchOff) + " минут " + str(secsToSwitchOff) + " секунд")

            self.writeResult("OK")
        elif pathList == list(["light", "on"]):
            reportText("Включаем свет")
            self.milightCommand(b'\xc2\x00\x55') # all white
            self.writeResult("OK")
        elif pathList[0] == "light" and pathList[1] == "brightness":
            reportText("Яркость " + pathList[2] + "%")
            # passed brightness is in format 0..100
            ba = bytearray(b'\x4E\x00\x55')
            ba[1] = int(0x2 + (0x15 * int(pathList[2]) / 100))
            self.milightCommand(bytes(ba)) # 
            self.writeResult("OK")
        elif pathList == list(["light", "low"]):
            self.milightCommand(b'\x45\x02\x55')
            self.writeResult("OK")
        elif pathList == list(["light", "off"]):
            reportText("Выключаем свет")
            self.milightCommand(b'\x46\x00\x55')
            self.writeResult("OK")

def run(server_class=ThreadingSimpleServer, handler_class=HomeHTTPHandler, port=8080):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)

    httpd = server_class(server_address, handler_class)

    def loop():
        timeToSleepWasReported = False
        while True: 
            time.sleep(5)
            
            httpd.loadM3UIfNeeded()

            minsToSwitchOff = int((httpd.sleepAt - time.time())/60)
            if (minsToSwitchOff == 1 or minsToSwitchOff == 2 or minsToSwitchOff%5==0):
                if not timeToSleepWasReported:
                    reportText("Телевизор выключится через " + str(minsToSwitchOff) + " минут")
                    timeToSleepWasReported = True
            else:
                timeToSleepWasReported = False
                
            # Let's check sleeping
            if httpd.sleepAt < time.time():
                httpd.adbShellCommand("input keyevent KEYCODE_POWER")
                sleepAt = httpd.timeToSleepNever()

    Thread(target=loop).start()  

    logging.info('Starting httpd...\n')
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    logging.info('Stopping httpd...\n')

if __name__ == '__main__':
    from sys import argv

    if len(argv) == 2:
        run(port=int(argv[1]))
    else:
        run()


