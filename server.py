#!/opt/bin/python3
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


from  urllib.parse import quote_plus
from urllib.request import urlopen
from socketserver import ThreadingMixIn
from threading import Thread

def nameForCompare(st):
    return st.lower()\
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
    urlopen("http://192.168.121.75/show?text="+quote_plus(text)).read()

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

    sleepAt = timeToSleepNever() # Sleep tablet at that time

    def adbShellCommand(self, command):
        resultStr = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read()
        if len(resultStr) > 0:
            subprocess.Popen("adb connect 192.168.121.166:5556", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()
            # And try again
            subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()

class HomeHTTPHandler(BaseHTTPRequestHandler):
    youtubeChannel = 0
    youtubeChannels = []

    def writeResult(self, res):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\"}").encode('utf-8'))

    def adbShellCommand(self, command):
        self.server.adbShellCommand(command)

    def stopCurrent(self):
        self.adbShellCommand("killall org.videolan.vlc")

    def playCurrent(self):
        self.stopCurrent()
        if len(self.youtubeChannels) == 0:
            self.loadM3U()       
        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -d \"" + 
                self.youtubeChannels[self.youtubeChannel]["url"] + 
                "\"")

    def milightCommand(self, cmd):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
        sock.sendto(cmd, ("192.168.121.35", 8899))

    def loadM3U(self):
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
       
        self.youtubeChannels.sort(key=lambda r:nameForCompare(r["name"]))
        ind = 0
        for ch in self.youtubeChannels:
            ch["index"] = ind
            ind = ind + 1
 
    def do_GET(self):
        logging.info("GET request,\nPath: %s\n\n", str(self.path))
        pathList = list(filter(None, self.path.split("/")))
        
        if len(pathList) == 0:
            self.loadM3U()

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            htmlContent = ""
            with open(os.path.dirname(os.path.abspath(__file__)) + '/web/index.html', 'r') as myfile:
                htmlContent = myfile.read()

            strr = ""
            
            currName = None
            btns = ""

            for ytb in self.youtubeChannels:
                if currName != None and nameForCompare(currName) != nameForCompare(ytb["name"]):
                    strr += "<div class='channel-line'>" + currName + "&nbsp;" + btns + "</div>" + "\n"
                    btns = ""
                btns += "<button class='action' data-url='/tablet/play/" + str(ytb["index"]) + "'  data-uri='" + ytb["url"] + "' data-name='" + ytb["name"] + "'> Play </button>" + "\n"
                currName = ytb["name"]

            if len(btns) > 0:
                strr += "<div class='channel-line'>" + currName + "&nbsp;" + btns + "</div>" + "\n"

            htmlContent = htmlContent.replace("<!--{{{channels}}}-->", strr)

            self.wfile.write(htmlContent.encode('utf-8'))
        else:
            self.writeResult("UNKNOWN CMD {}".format(self.path))

    def do_POST(self):
        pathList = list(filter(None, self.path.split("/")))
        if pathList[0] == "init":
            self.loadM3U()
            self.send_response(200)
        elif pathList[0] == "tablet" and pathList[1] == "play":
            if len(self.youtubeChannels) == 0:
                self.loadM3U()

            if (len(pathList) > 2):
                self.youtubeChannel = int(pathList[2])
                ytb = self.youtubeChannels[self.youtubeChannel]
                reportText("Включаем " + ytb["name"] + "........")
                
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "stop"]):
            self.youtubeChannel = self.youtubeChannel + 1
            self.stopCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "playagain"]):
            self.stopCurrent()
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "playnext"]):
            self.youtubeChannel = self.youtubeChannel + 1
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "playprev"]):
            self.youtubeChannel = self.youtubeChannel - 1
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
        elif pathList == list(["tablet", "reboot"]):
            self.adbShellCommand("reboot")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "sleepin":
            self.server.sleepAt = time.time() + int(pathList[2])
            
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

def run(server_class=ThreadingSimpleServer, handler_class=HomeHTTPHandler, port=8000):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)

    httpd = server_class(server_address, handler_class)

    def loop():
        while True: 
            time.sleep(15)
            minsToSwitchOff = int((httpd.sleepAt - time.time())/60)
            if minsToSwitchOff == 1 or minsToSwitchOff == 2 or minsToSwitchOff%5==0:
                reportText("Телевизор выключится через " + str(minsToSwitchOff) + " минут")
            # Let's check sleeping
            if httpd.sleepAt < time.time():
                httpd.adbShellCommand("input keyevent KEYCODE_POWER")
                sleepAt = self.timeToSleepNever()

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


