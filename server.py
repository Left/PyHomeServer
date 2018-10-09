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
import base64
import urllib
import websocket

from urllib.parse import quote_plus
from urllib.request import urlopen
from socketserver import ThreadingMixIn
from threading import Thread

class Gender:
    on = ""
    off = ""

    def __init__(self, on, off):
        self.on = on
        self.off = off

gMale = Gender("включен", "выключен")
gFemale = Gender("включена", "выключена")
gMany = Gender("включены", "выключены")
gThird = Gender("включено", "выключено")

httpd = None
pingig = 1
allWs = []
clockWs = []

relays = {\
    93: [\
        { "name": "Лампа на шкафу", "state": False, "gender": gFemale },\
        { "name": "Колонки", "state": False, "gender": gMany },\
        { "name": "Освещение в коридоре", "state": False, "gender": gThird },\
        { "name": "Пустая релюха", "state": False, "gender": gFemale },\
    ],\
    112: [\
        { "name": "Потолочная лампа на кухне", "state": False, "gender": gFemale },\
        { "name": "Лента освещения на кухне", "state": False, "gender": gFemale },\
    ],\
}

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

def asyncHttpReq(urlToFetch):
    def open_website(url):
        return urlopen(url)

    Thread(target=open_website, args=[urlToFetch]).start()

def reportText(text):
    for ws in clockWs:
        ws.send("{ \"type\": \"show\", \"text\": \"" + text + "\" }")
    #    except Exception as e:
    #       # Nothing to do?
    # asyncHttpReq("http://192.168.121.75/show?text="+quote_plus(text))

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

    loadedChannelsAt = 0
    youtubeChannel = ""
    youtubeChannels = []
    youtubeChannelsByIds = {}

    sleepAt = timeToSleepNever() # Sleep tablet at that time

    def __init__(self, *args):
        HTTPServer.__init__(self, *args)
        self.loadM3U()

    def adbShellCommand(self, command):
        return self.server.adbShellCommand(command)

    def volUp(self):
        reportText("Громче")
        self.adbShellCommand("input keyevent KEYCODE_VOLUME_UP")

    def volDown(self):
        reportText("Тише")
        self.adbShellCommand("input keyevent KEYCODE_VOLUME_DOWN")

    def switchRelay(self, controller, relay):
        currRelay = relays[controller][relay]
        
        asyncHttpReq("http://192.168.121."+str(controller)+"/switch?id="+str(relay)+"&on=" + ("false" if currRelay["state"] else "true"))

        currRelay["state"] = not currRelay["state"]

        reportText(currRelay["name"] + " " + (currRelay["gender"].on if currRelay["state"] else currRelay["gender"].off) + "")

    def adbShellCommand(self, command):
        process = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        resultOut, resultErr = process.communicate()
        if len(resultErr) > 0:
            subprocess.Popen("adb connect 192.168.121.166:5556", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()
            # And try again
            process = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            resultOut, resultErr = process.communicate()
        return resultOut

    def loadM3UIfNeeded(self):
        if len(self.youtubeChannels) == 0 or (time.time() - self.loadedChannelsAt) > 3600:
            # logging.info("Last load at " + str(time.time() - self.loadedChannelsAt))
            # we load channels each hour or on start
            self.loadM3U()

    def loadM3U(self):
        try:
            logging.info("LOADING CHANNELS")

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

            # response = urlopen("http://acetv.org/js/data.json?0.26020398076972606").read().decode("utf-8")
            response = urlopen("http://pomoyka.win/trash/ttv-list/as.json").read().decode("utf-8")
            # logging.info(response)
            channels = json.loads(response)
            
            self.youtubeChannels = []

            for ch in channels["channels"]:
                self.youtubeChannels.append({ "name": ch["name"], "url": "http://192.168.121.38:8000/pid/" + ch["url"] + "/stream.mp4", "cat": ch["cat"] })

            self.youtubeChannels.sort(key=lambda r:nameForCompare(r))
            for ch in self.youtubeChannels:
                urlHash = bytes(hashlib.sha256(ch["url"].encode('utf-8')).digest())
                ch["id"] = urlHash.hex()
                if ch["id"] in self.youtubeChannelsByIds and self.youtubeChannelsByIds[ch["id"]]["url"] != ch["url"]:
                    logging.error("HASH CLASH: " + str(ch["id"]) + " " + ch["url"] + " " + self.youtubeChannelsByIds[ch["id"]]["url"]) 
                else:
                    self.youtubeChannelsByIds[ch["id"]] = ch

            with open(os.path.dirname(os.path.abspath(__file__)) + "channels.json", "w") as write_file:
                write_file.write(json.dumps(self.youtubeChannels))

            self.loadedChannelsAt = time.time()
            logging.info("LOADED CHANNELS")
        except Exception as e:
            logging.info("FAILED TO LOAD CHANNELS:" + str(e))

def webSocketLoop():
    last = {}

    def on_message(ws, message):
        msg = json.loads(message)
        
        if msg["type"] == "ir_key":
            now = msg["day"] * 24 * 60 * 60 * 1000 + msg["timems"]
            if not (msg["remote"] in last):
                last[msg["remote"]] = 0

            if now - last[msg["remote"]] > 200:
                last[msg["remote"]] = now
                if msg["key"] == "volume_up":
                    httpd.volUp()
                elif msg["key"] == "volume_down":
                    httpd.volDown()
                if msg["key"] == "n1":
                    httpd.switchRelay(93, 0)
                if msg["key"] == "n2":
                    httpd.switchRelay(93, 1)
                if msg["key"] == "n3":
                    httpd.switchRelay(93, 2)
                if msg["key"] == "n4":
                    httpd.switchRelay(93, 3)
                if msg["key"] == "n5":
                    httpd.switchRelay(112, 0)
                if msg["key"] == "n6":
                    httpd.switchRelay(112, 1)
                if msg["key"] == "n0":
                    httpd.adbShellCommand("am start -a android.intent.action.VIEW -d \"http://www.youtube.com/watch?v=K59KKnIbIaM\" --ez force_fullscreen true")
                    reportText("Включаем Россия 24")
                else:
                    print(msg["remote"] + " " + msg["key"])
        elif msg["type"] == "log":
            print(msg["val"])
        else:
            print(msg)

    def on_error(ws, error):
        print(error)

    def on_close(ws):
        clockWs.remove(ws)
        allWs.remove(ws)
        print("### closed ###")

    ws = websocket.WebSocketApp("ws://192.168.121.75:8081/",
                            on_message = on_message,
                            on_error = on_error,
                            on_close = on_close)

    allWs.append(ws)
    clockWs.append(ws)

    ws.run_forever()

    print("Web socket is closed!")

class HomeHTTPHandler(BaseHTTPRequestHandler):
    def writeResult(self, res):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\"}").encode('utf-8'))

    def stopCurrent(self):
        httpd.adbShellCommand("am force-stop org.videolan.vlc")

    def playCurrent(self):
        self.stopCurrent()
        logging.info(self.server.youtubeChannelsByIds[self.server.youtubeChannel]["url"])
        httpd.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -d \"" + 
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
                    + ytb["id"] + "'  data-uri='"\
                    + ytb["url"] + "' data-name='" + ytb["name"] + "'>[    Play    ]</button>" + "\n"
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
        elif pathList == list(["tablet", "screen"]):
            self.send_response(200)
            self.send_header('Content-type', 'image/bmp')
            self.end_headers()

            self.wfile.write(re.sub(b'\r\n', b'\n', httpd.adbShellCommand("screencap -p")))
        else:
            self.writeResult("UNKNOWN CMD {}".format(self.path))

    def do_POST(self):
        pathList = list(filter(None, self.path.split("/")))
        if pathList[0] == "init":
            self.send_response(200)
        elif pathList[0] == "tablet" and pathList[1] == "play":
            if (len(pathList) > 2):
                self.server.youtubeChannel = pathList[2]
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
            httpd.volUp()
            self.writeResult("OK")
        elif pathList == list(["tablet", "voldown"]):
            httpd.volDown()
            self.writeResult("OK")
        elif pathList == list(["tablet", "onoff"]):
            httpd.adbShellCommand("input keyevent KEYCODE_POWER")
            self.writeResult("OK")
        elif pathList == list(["tablet", "russia24"]):
            httpd.adbShellCommand("am start -a android.intent.action.VIEW -d \"http://www.youtube.com/watch?v=K59KKnIbIaM\" --ez force_fullscreen true")
            self.writeResult("OK")
        elif pathList == list(["tablet", "youtube", "stop"]):
            httpd.adbShellCommand("am force-stop com.google.android.youtube")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "youtube":
            httpd.adbShellCommand("am start -a android.intent.action.VIEW -d \"http://www.youtube.com/watch?v=" + pathList[2] + "\" --ez force_fullscreen true")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "youtubeURL":
            logging.info('Playing ' + urllib.parse.unquote(pathList[2]))
            httpd.adbShellCommand("am start -a android.intent.action.VIEW -d \"" + urllib.parse.unquote(pathList[2])\
                .replace("&", "\&")\
                .replace("https:", "http:")\
                + "\" --ez force_fullscreen true")
            self.writeResult("OK")
        elif pathList == list(["tablet", "reboot"]):
            httpd.adbShellCommand("reboot")
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
        elif pathList[0] == "relay":
            asyncHttpReq("http://192.168.121." + pathList[1] + "/switch?id=" + pathList[2] + "&on=" + pathList[3])
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

    global httpd
    global pingig
    httpd = server_class(server_address, handler_class)

    def loop():
        timeToSleepWasReported = False
        while True: 
            time.sleep(3)
            
            httpd.loadM3UIfNeeded()

            #asyncHttpReq("http://192.168.121.112/")
            #asyncHttpReq("http://192.168.121.93/")

            #for ws in allWs:
            #    pingig = pingig + 1
            #    ws.send("{ \"type\": \"ping\", \"pingid\": \"" + str(pingig) + "\" }")

            minsToSwitchOff = int((httpd.sleepAt - time.time())/60)
            if minsToSwitchOff < 1440 and (minsToSwitchOff == 1 or minsToSwitchOff == 2 or minsToSwitchOff%5==0):
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
    Thread(target=webSocketLoop).start()

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


