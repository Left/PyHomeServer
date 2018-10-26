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
import datetime
import json
import hashlib
import struct
import base64
import urllib
import websocket
import traceback
import binascii
import asyncio

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
    clockWs.send("{ \"type\": \"show\", \"text\": \"" + text + "\" }")

def timeBefore(timeInSecs):
    hoursToSwitchOff = int((timeInSecs - time.time())/60/60)
    minsToSwitchOff = int((timeInSecs - time.time())/60)%60
    secsToSwitchOff = int((timeInSecs - time.time())%60)
    return (str(hoursToSwitchOff) + "часов " if hoursToSwitchOff > 0 else "") + str(minsToSwitchOff) + " минут " + str(secsToSwitchOff) + " секунд"


class MiLight:
    on = False
    brightness = 50

    def __init__(self, ip, port):
        self.ip = ip
        self.port = port

    def allWhite(self):
        self.on = True
        self.milightCommand(b'\xc2\x00\x55') # all white

    def brightness(self, percent):
        # passed brightness is in format 0..100
        ba = bytearray(b'\x4E\x00\x55')
        ba[1] = int(0x2 + (0x15 * percent / 100))
        self.brightness = percent
        self.milightCommand(bytes(ba)) # 

    def off(self):
        self.on = False
        self.milightCommand(b'\x46\x00\x55')

    def milightCommand(self, cmd):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # UDP
        sock.sendto(cmd, (self.ip, self.port))


milight = MiLight("192.168.121.35", 8899)


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass

    loadedChannelsAt = 0
    youtubeChannel = ""
    youtubeChannels = []
    youtubeChannelsByIds = {}

    sleepAt = timeToSleepNever() # Sleep tablet at that time
    wakeAt = timeToSleepNever()

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

    def turnRelay(self, relayComm, relay, on):       
        relayComm.send("{ \"type\": \"switch\", \"id\": \"" + str(relay) + "\", \"on\": \"" + ("true" if on else "false") + "\" }")

        logging.info("Turned " + ("on" if on else "off") + " relay " + str(relay) + " at " + relayComm.ip)

        currRelay = relayComm.relays[relay]
        currRelay["state"] = on

        reportText(currRelay["name"] + " " + (currRelay["gender"].on if on else currRelay["gender"].off) + "")

    def switchRelay(self, relayComm, relay):
        self.turnRelay(relayComm, relay, not relayComm.relays[relay]["state"])

    def adbShellCommand(self, command):
        logging.info("adb shell " + command)
        process = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        resultOut, resultErr = process.communicate()
        if len(resultErr) > 0:
            subprocess.Popen("adb connect 192.168.121.166:5556", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()
            # And try again
            process = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            resultOut, resultErr = process.communicate()
        return resultOut

    def stopCurrent(self):
        self.adbShellCommand("am force-stop org.videolan.vlc")

    def playCurrent(self):
        self.stopCurrent()
        logging.info(self.youtubeChannelsByIds[self.youtubeChannel]["url"])
        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -d \"" + 
                self.youtubeChannelsByIds[self.youtubeChannel]["url"] + 
                "\"")

    def isTabletAwake(self):
        allTheLines = self.adbShellCommand("dumpsys power").decode("utf-8").splitlines()

        return "true" in next(filter(lambda ll: 'mHoldingWakeLockSuspendBlocker=' in ll, allTheLines))
        
    def switchTable(self):
        self.adbShellCommand("input keyevent KEYCODE_POWER")

    def loadM3UIfNeeded(self):
        if len(self.youtubeChannels) == 0 or (time.time() - self.loadedChannelsAt) > 3600:
            # logging.info("Last load at " + str(time.time() - self.loadedChannelsAt))
            # we load channels each hour or on start
            self.loadM3U()

    def awakeTabletIfNeeded(self):
        if not self.isTabletAwake():
            self.switchTable()
        self.turnRelay(relayRoom, 1, True)

    def playYoutubeURL(self, youtubeURL):
        self.awakeTabletIfNeeded()
        httpd.stopCurrent()

        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -a android.intent.action.VIEW -d \"" + youtubeURL\
                .replace("&", "\&")\
                .replace("https://", "http://")\
                + "\" --ez force_fullscreen true")

    def playYoutube(self, youtubeId):
        self.awakeTabletIfNeeded()
        httpd.stopCurrent()

        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -a android.intent.action.VIEW -d \"http://www.youtube.com/watch?v=" + youtubeId + "\" --ez force_fullscreen true")

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

class DeviceCommunicationChannel():
    pingig = 0
    ws = None
    lastMsgReceived = 0

    def __init__(self, ip, packetsProcessor, relays):
        self.ip = ip
        self.packetsProcessor = packetsProcessor
        self.relays = relays

    def start(self):
        Thread(target=self.webSocketLoop).start()

    def send(self, str):
        try:
            self.ws.send(str)
        except Exception:
            self.ws.close()
            traceback.print_exc()
            pass
        

    def ping(self):
        if (time.time() - self.lastMsgReceived) > 6:
            self.ws.close()
        else:
            self.pingig += 1
            self.ws.send("{ \"type\": \"ping\", \"pingid\": \"" + str(self.pingig) + "\" }")

    def webSocketLoop(self):
        def on_message(ws, message):
            try:
                msg = json.loads(message)
                self.lastMsgReceived = time.time()
                # logging.info("Received from " + self.ip + ": " + message)

                if "type" in msg and msg["type"] == "log":
                    # Just logging, print it
                    logging.info(self.ip + ": " + msg["val"])
                else:
                    # let lambda process it
                    self.packetsProcessor(msg)           
            except Exception:
                logging.info(self.ip + ": Exception for connection")
                # traceback.print_exc()
                pass

        def on_error(ws, error):
            logging.info(self.ip + error)
            self.ws.close()

        def on_close(ws):
            logging.info(self.ip + ": ### closed ### ")

        while True:
            self.lastMsgReceived = time.time()
            self.ws = websocket.WebSocketApp("ws://" + self.ip + ":8081/",
                                    on_message = on_message,
                                    on_error = on_error,
                                    on_close = on_close)
            self.ws.run_forever()
            logging.info(self.ip + ": Web socket is closed")

class HomeHTTPHandler(BaseHTTPRequestHandler):
    def writeResult(self, res):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\"}").encode('utf-8'))

    def doInSafe(self, lam):
        try:
            lam(self)
        except Exception as e:
            traceback.print_exc()
            self.send_response(500)
            self.send_header('Content-type', 'text/plain;charset=utf-8')
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

    def do_GET(self):
        self.doInSafe(lambda _: self.do_GET_impl())

    def do_POST(self):
        self.doInSafe(lambda _: self.do_POST_impl())

    def do_GET_impl(self):
        logging.info("GET request,\nPath: %s", str(self.path))
        # pathList = list(filter(None, self.path.split("/")))
        pathList = list(filter(None, self.path.split("?")[0].split("/")))
        
        if len(pathList) == 0 or ".html" in pathList[0]:
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            htmlContent = ""
            with open(os.path.dirname(os.path.abspath(__file__)) + '/web/' + ("index.html" if len(pathList) == 0 else pathList[0]), 'r') as myfile:
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
        elif pathList == list(["esp8266", "update"]):
            logging.info("esp8266update")

            fullFileName = os.path.dirname(os.path.abspath(__file__)) + '/firmware/esp8266update.bin'
            hash_md5 = hashlib.md5()
            with open(fullFileName, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    hash_md5.update(chunk)
            md5str = hash_md5.hexdigest()

            logging.info("responding")

            self.send_response(200)
            self.send_header('Content-Type', 'application/octet-stream')
            self.send_header('Content-Disposition', 'attachment; filename=esp8266update.bin')
            self.send_header('Content-Length', os.path.getsize(fullFileName))
            self.send_header('Content-Transfer-Encoding', 'binary')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Pragma', 'no-cache')
            self.send_header('x-MD5', md5str)
            self.end_headers()

            with open(fullFileName, 'rb') as myfile:
                self.wfile.write(myfile.read())
        elif pathList == list(["tablet", "screen"]):
            self.send_response(200)
            self.send_header('Content-type', 'image/bmp')
            self.end_headers()

            t = time.time()

            rawCapture = httpd.adbShellCommand("screencap -p")

            logging.info("captured screen " + str(time.time() - t))

            screenRaw = re.sub(b'\r\n', b'\n', rawCapture)

            logging.info("decoding screen " + str(time.time() - t))

            self.wfile.write(screenRaw)
            self.wfile.flush()
            
        else:
            self.writeResult("UNKNOWN CMD {}".format(self.path))

    def do_POST_impl(self):
        pathList = list(filter(None, self.path.split("?")[0].split("/")))
        logging.info(self.path + " -> " + str(pathList))
        if pathList[0] == "init":
            self.send_response(200)
        elif pathList[0] == "tablet" and pathList[1] == "play":
            if (len(pathList) > 2):
                self.server.youtubeChannel = pathList[2]
                ytb = self.server.youtubeChannelsByIds[self.server.youtubeChannel]
                reportText("Включаем " + ytb["name"])
                
            httpd.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "stop"]):
            httpd.stopCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "playagain"]):
            httpd.stopCurrent()
            httpd.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "volup"]):
            httpd.volUp()
            self.writeResult("OK")
        elif pathList == list(["tablet", "voldown"]):
            httpd.volDown()
            self.writeResult("OK")
        elif pathList == list(["tablet", "on"]):
            if not httpd.isTabletAwake():
                httpd.switchTable()
            self.writeResult("OK")
        elif pathList == list(["tablet", "off"]):
            if httpd.isTabletAwake():
                httpd.switchTable()
            self.writeResult("OK")
        elif pathList == list(["tablet", "onoff"]):
            httpd.switchTable()
            self.writeResult("OK")
        elif pathList == list(["tablet", "russia24"]):
            httpd.playYoutube("K59KKnIbIaM")
            self.writeResult("OK")
        elif pathList == list(["tablet", "radioParadise"]):
            httpd.playYoutubeURL("https://www.radioparadise.com/m3u/mp3-192.m3u")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "tap":
            httpd.adbShellCommand("input tap " + pathList[2] + " " + pathList[3])
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "text":
            httpd.adbShellCommand("input text '" + urllib.parse.unquote(pathList[2]) + "'")
            self.writeResult("OK")
        elif pathList == list(["tablet", "youtube", "stop"]):
            httpd.adbShellCommand("am force-stop com.google.android.youtube")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "youtube":
            httpd.playYoutube(pathList[2])
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] ==  "youtubeURL":
            httpd.playYoutubeURL(urllib.parse.unquote(pathList[2]))
            self.writeResult("OK")
        elif pathList == list(["tablet", "reboot"]):
            httpd.adbShellCommand("reboot")
            self.writeResult("OK")
        elif pathList == list(["self", "reboot"]):
            subprocess.Popen("reboot", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read() # Reboot self
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "sleepin":
            self.server.sleepAt = time.time() + int(pathList[2])

            reportText("Телевизор выключится через " + timeBefore(httpd.sleepAt))

            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "wakeat":
            hrs = int(pathList[2])
            mins = int(pathList[3])
            now = datetime.datetime.now()
            if hrs < now.hour or (hrs == now.hour and mins < now.minute):
                #tomorrow
                httpd.wakeAt = time.time() + ((23 - now.hour)*60 + (59 - now.minute) + hrs*60 + mins)*60
            else:
                #today
                httpd.wakeAt = time.time() + ((hrs - now.hour)*60 + (mins - now.minute))*60
            reportText("Телевизор включится через " + timeBefore(httpd.wakeAt))

            self.writeResult("OK")
        elif pathList == list(["light", "on"]):
            reportText("Включаем свет")
            milight.allWhite()
            self.writeResult("OK")
        elif pathList[0] == "relay":
            for ws in allWs:
                if ws.ip == ("192.168.121." + pathList[1]):
                    httpd.turnRelay(ws, int(pathList[2]), pathList[3] == "true")
        elif pathList[0] == "light" and pathList[1] == "brightness":
            reportText("Яркость " + pathList[2] + "%")
            milight.brightness(int(pathList[2]))
            self.writeResult("OK")
        elif pathList == list(["light", "off"]):
            reportText("Выключаем свет")
            milight.off()
            self.writeResult("OK")

last = {}

def clockRemoteCommands(msg):
    if "type" in msg:
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
                    httpd.switchRelay(relayRoom, 0)
                if msg["key"] == "n2":
                    httpd.switchRelay(relayRoom, 1)
                if msg["key"] == "n3":
                    httpd.switchRelay(relayRoom, 2)
                if msg["key"] == "n4":
                    httpd.switchRelay(relayRoom, 3)
                if msg["key"] == "n5":
                    httpd.switchRelay(relayKitchen, 0)
                if msg["key"] == "n6":
                    httpd.switchRelay(relayKitchen, 1)
                if msg["key"] == "n7":
                    reportText("Включаем свет")
                    if milight.on:
                        milight.off()
                    else:
                        milight.allWhite()
                if msg["key"] == "n0":
                    httpd.playYoutube("K59KKnIbIaM")
                    reportText("Включаем Россия 24")
                else:
                    print(msg["remote"] + " " + msg["key"])
        else:
            print("Unrecognized type:" + msg["type"])
    #elif "result" in msg:
    #    print(msg["result"])

def relayRemoteCommands(msg):
    if "type" in msg:
        # Nothing to do ATM?
        print(msg)

clockWs = DeviceCommunicationChannel("192.168.121.75", clockRemoteCommands, [])
relayRoom = DeviceCommunicationChannel("192.168.121.93", clockRemoteCommands, [\
    { "name": "Лампа на шкафу", "state": False, "gender": gFemale },\
    { "name": "Колонки", "state": False, "gender": gMany },\
    { "name": "Освещение в коридоре", "state": False, "gender": gThird },\
    { "name": "Пустая релюха", "state": False, "gender": gFemale },\
])

relayKitchen = DeviceCommunicationChannel("192.168.121.112", clockRemoteCommands, [\
    { "name": "Потолочная лампа на кухне", "state": False, "gender": gFemale },\
    { "name": "Лента освещения на кухне", "state": False, "gender": gFemale },\
])

allWs = [ clockWs, relayRoom, relayKitchen ]

def run(server_class=ThreadingSimpleServer, handler_class=HomeHTTPHandler, port=8080):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)

    global httpd
    httpd = server_class(server_address, handler_class)

    def loop():
        timeToSleepWasReported = False
        while True:
            try:
                time.sleep(3)
                
                httpd.loadM3UIfNeeded()

                for ws in allWs:
                    try:
                        ws.ping()
                    except Exception:
                        traceback.print_exc()

                minsToSwitchOff = int((httpd.sleepAt - time.time())/60)
                if minsToSwitchOff < 1440 and (minsToSwitchOff == 1 or minsToSwitchOff == 2 or minsToSwitchOff%5==0):
                    if not timeToSleepWasReported:
                        reportText("Телевизор выключится через " + timeBefore(httpd.sleepAt))
                        timeToSleepWasReported = True
                else:
                    timeToSleepWasReported = False
                    
                # Let's check sleeping
                if httpd.sleepAt < time.time():
                    logging.info("Sleeping!!!")
                    reportText("Выключаемся...")
                    milight.off()
                    httpd.turnRelay(relayRoom, 0, False)
                    time.sleep(1)
                    httpd.turnRelay(relayRoom, 1, False)
                    time.sleep(1)
                    httpd.turnRelay(relayRoom, 2, False)
                    time.sleep(1)
                    httpd.turnRelay(relayKitchen, 0, False)
                    time.sleep(1)
                    httpd.turnRelay(relayKitchen, 1, False)
                    if httpd.isTabletAwake():
                        httpd.stopCurrent()
                        httpd.adbShellCommand("input keyevent KEYCODE_POWER")

                    httpd.sleepAt = timeToSleepNever()

                # logging.info("Time: " + str(time.time()) + " " + str(httpd.wakeAt))

                if httpd.wakeAt < time.time():
                    logging.info("Waking!!!")
                    reportText("Включаемся...")
                    milight.allWhite()
                    httpd.turnRelay(relayRoom, 0, True)
                    time.sleep(1)
                    httpd.turnRelay(relayRoom, 1, True)
                    if not httpd.isTabletAwake():
                        httpd.stopCurrent()
                        httpd.adbShellCommand("input keyevent KEYCODE_POWER")
                    httpd.playYoutube("K59KKnIbIaM")
                    httpd.wakeAt = timeToSleepNever()

            except Exception:
                traceback.print_exc()

    def aceThreadLoop():
        @asyncio.coroutine
        def client(loop):
            logging.info("========== : ============")

            reader, writer = yield from asyncio.open_connection('0.0.0.0', 62062, loop=loop)

            logging.info("========== : ============")

            writer.write(b'HELLOBG version=1\r\n')

            logging.info("========== HELLOWED ============")

            def readLine():
                resp = b''
                while not (b'\r\n' in resp):
                    data = yield from reader.read(1)
                    resp += data

                resp = resp[0:len(resp)-2]

                return resp

            resp = yield from readLine()

            logging.info("========== RECEIVED ============ " + resp) 

            # Remove HELLOTS
            resp = resp[len(b'HELLOTS '):]

            params = dict(map(lambda x: tuple(filter(lambda f: len(f) > 0, x.split('='))), resp.decode("utf-8").split(' ')))
            # {'version_code': '3010500', 'version': '3.1.5', 'http_port': '6878', 'key': '59c51a4a44', 'bmode': '0'}

            # Ace Stream API key
            # You probably shouldn't touch this
            acekey = b'n51LvQoTlJzNGaFxseRK-uvnvX-sD4Vm5Axwmc4UcoD-jruxmKsuJaH0eVgE'

            readyMsg = b'READY key=' + acekey.split(b'-')[0] + b'-' + \
                            (hashlib.sha1(params["key"].encode("ascii") + acekey).hexdigest()).encode("ascii") + b'\r\n'

            logging.info("Send:" + readyMsg.decode("utf-8"))

            writer.write(readyMsg)
            
            resp = yield from readLine()

            logging.info("Got:" + resp.decode("utf-8"))

            writer.write(b'LOADASYNC 523 PID 826a603345a186ffe09391156d29a2d512445c48\r\n')

            resp = yield from readLine()

            logging.info("Got:" + resp.decode("utf-8"))

            # writer.write(b'START PID 84f8cdc56625e9ea5ac73bc1a89df72872cf21a4 0\r\n')
            writer.write(b'START PID 826a603345a186ffe09391156d29a2d512445c48 0\r\n')
            # writer.write(b'START PID 58148f4f4dded1e0fe01b17db26b070da5985df6 0\r\n')

            while True:
                resp = yield from readLine()
                logging.info("Got:" + resp.decode("utf-8"))

                if resp.startswith(b'PLAY '):
                    writer.write(b"DUR " + resp[len(b'PLAY'):] + b" 201964\r\n")
                    writer.write(b"PLAYBACK " + resp[len(b'PLAY'):] + b" 0\r\n")
                    

            #print('Close the socket')
            #writer.close()

        #aceClient = AceClient("0.0.0.0", 62062)
        #loop = asyncio.get_event_loop()
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(client(loop))
        loop.close()

    # Thread(target=aceThreadLoop).start()
    Thread(target=loop).start()
    
    # Start all web communications
    for ws in allWs:
        ws.start()

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


