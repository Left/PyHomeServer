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
import sys
import copy 

from urllib.parse import quote_plus, urlparse
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

    def changeBrightness(self, percent):
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
    youtubeHistory = []
    youtubeChannelsByIds = {}
    youtubeChannelsByUrls = {}

    settings = {}
    sleepAt = timeToSleepNever() # Sleep tablet at that time
    wakeAt = timeToSleepNever()

    # this URL is currently playing
    nowPlayingUrl = None

    def __init__(self, *args):
        HTTPServer.__init__(self, *args)
        self.loadM3U()

        try: 
            with open(os.path.dirname(os.path.abspath(__file__)) + "/history.json", "r") as write_file:
                self.youtubeHistory = json.loads(write_file.read())

            with open(os.path.dirname(os.path.abspath(__file__)) + "/settings.json", "r") as write_file:
                self.settings = json.loads(write_file.read())
                self.sleepAt = self.settings["sleepAt"] if "sleepAt" in self.settings else timeToSleepNever()
                self.wakeAt = self.settings["wakeAt"] if "wakeAt" in self.settings else timeToSleepNever()
        except Exception as e:
            pass # Do nothing   

    def adbShellCommand(self, command):
        return self.server.adbShellCommand(command)

    def volUp(self):
        reportText("Vol+  ")
        if httpd.getSoundVolInPercent() < 100:
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_UP")
        reportText("Vol " + str(httpd.getSoundVolInPercent()) + "%   ")

    def volDown(self):
        reportText("Vol-  ")
        self.adbShellCommand("input keyevent KEYCODE_VOLUME_DOWN")
        reportText("Vol " + str(httpd.getSoundVolInPercent()) + "%   ")

    def turnRelay(self, relayComm, relay, on):
        relayComm.send("{ \"type\": \"switch\", \"id\": \"" + str(relay) + "\", \"on\": \"" + ("true" if on else "false") + "\" }")

        logging.info("Turned " + ("on" if on else "off") + " relay " + str(relay) + " at " + relayComm.ip)

        currRelay = relayComm.relays[relay]
        stateWasChanged = currRelay["state"] != on
        currRelay["state"] = on

        if stateWasChanged:
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
        self.nowPlayingUrl = None
        self.adbShellCommand("am force-stop org.videolan.vlc")

    def getSoundVolInPercent(self):
        allTheLines = self.adbShellCommand("dumpsys audio").decode("utf-8").split('- STREAM_')
        musicLines = next(filter(lambda ll: ll.startswith('MUSIC:'), allTheLines))
        muteCountLine = next(filter(lambda ll: ll.startswith("   Mute count:"), musicLines.splitlines()))
        if (muteCountLine != '   Mute count: 0'):
            return 0 # we're muted, no need to check further

        currVolLine = next(filter(lambda ll: ll.startswith("   Current:"), musicLines.splitlines()))
        allValues = currVolLine.split(', ')
        currVol = next(filter(lambda ll: ll.startswith("2:"), allValues))
        maxVol = next(filter(lambda ll: ll.startswith("1000:"), allValues))

        retVol = int(float(currVol.split(': ')[1]) / float(maxVol.split(': ')[1]) * 100)
        
        return retVol

    def playCurrent(self):
        self.stopCurrent()
        
        url = self.youtubeChannelsByIds[self.youtubeChannel]["url"]
        self.playOnTablet(url, url)

    def isTabletAwake(self):
        allTheLines = self.adbShellCommand("dumpsys power").decode("utf-8").splitlines()

        return "true" in next(filter(lambda ll: 'mHoldingWakeLockSuspendBlocker=' in ll, allTheLines))
        
    def playPause(self):
        self.adbShellCommand("input keyevent KEYCODE_SPACE")

    def toggleTabletPower(self):
        self.adbShellCommand("input keyevent KEYCODE_POWER")

    def loadM3UIfNeeded(self):
        if len(self.youtubeChannels) == 0 or (time.time() - self.loadedChannelsAt) > 3600:
            # logging.info("Last load at " + str(time.time() - self.loadedChannelsAt))
            # we load channels each hour or on start
            self.loadM3U()

    def awakeTabletIfNeeded(self):
        if not self.isTabletAwake():
            self.toggleTabletPower()
        self.turnRelay(relayRoom, 1, True)

    def saveYoutubeHistory(self):
        with open(os.path.dirname(os.path.abspath(__file__)) + "/history.json", "w") as write_file:
            write_file.write(json.dumps(self.youtubeHistory))

    def saveSettings(self):
        with open(os.path.dirname(os.path.abspath(__file__)) + "/settings.json", "w") as write_file:
            write_file.write(json.dumps(self.settings))

    def playOnTablet(self, url, name):
        # if name is URL, let's find it's name (if possible)
        if name in self.youtubeChannelsByUrls:
            name = self.youtubeChannelsByUrls[name]["name"]

        reportText("+ " + name)

        existingEl = filter(lambda e: e["url"] == url, self.youtubeHistory)
        el = next(existingEl, False)

        if not el:
            if len(self.youtubeHistory) > 40:
                # remove first with no "channel" assigned
                self.youtubeHistory.remove(next(filter(lambda x: not "channel" in x, self.youtubeHistory)))

            self.youtubeHistory.append({\
                "name": name,\
                "url": url,\
                "cat": "history"})
        else:
            self.youtubeHistory.remove(el)
            self.youtubeHistory.append(el)

        self.saveYoutubeHistory()

        # logging.info(json.dumps(self.youtubeHistory))

        self.awakeTabletIfNeeded()

        self.stopCurrent()

        self.nowPlayingUrl = url

        self.adbShellCommand("am start -n org.videolan.vlc/org.videolan.vlc.gui.video.VideoPlayerActivity -a android.intent.action.VIEW -d \"" + url\
                .replace("&", "\&")\
                + "\" --ez force_fullscreen true")

    def getByChannelOrNone(self, n):
        return next(filter(lambda x: "channel" in x and x["channel"] == n, httpd.youtubeHistory), None)

    def getHistoryByUrlOrNone(self, url):
        return next(filter(lambda x: "url" in x and x["url"] == url, httpd.youtubeHistory), None)

    def playYoutubeURL(self, youtubeURL):
        splitUrlRes = urlparse(youtubeURL)
        if (splitUrlRes.netloc == 'www.youtube.com'):
            #logging.info(splitUrlRes.netloc)
            parsedQuery = urllib.parse.parse_qs(splitUrlRes.query)
            youtubeId = parsedQuery['v'][0]
            self.playYoutube(youtubeId)
        elif (splitUrlRes.netloc == 'youtu.be'):
            #logging.info(splitUrlRes.path.split('/')[1])
            self.playYoutube(next(filter(bool, splitUrlRes.path.split('/'))))
            # https://youtu.be/xwAKjlvSNq8
        else:
            self.playOnTablet(youtubeURL, youtubeURL)

    def playYoutube(self, youtubeId):
        text = "Youtube video " + youtubeId
        try:
            k = "AIzaSyBTB" +\
                "nuj6KV1TgQhg2MY" +\
                "qZrB1EQdmS9yhuM"

            response = urlopen("https://www.googleapis.com/youtube/v3/videos?part=id%2C+snippet&key=" + k + "&id=" + youtubeId).read().decode("utf-8")
            respJSON = json.loads(response)
            itemsNode = respJSON["items"]

            if (len(itemsNode) > 0):
                text = itemsNode[0]["snippet"]["title"]
        except Exception as e:
            pass # Do nothing

        self.playOnTablet("https://www.youtube.com/watch?v=" + youtubeId, text)

    def loadM3U(self):
        try:
            logging.info("LOADING CHANNELS")

            self.youtubeChannels = []
            id = 0

            for iptvUrl in [\
                ["1_IPTV", "http://iptviptv.do.am/_ld/0/1_IPTV.m3u"], 
                # ["4_VLC", "http://iptviptv.do.am/_ld/0/4_VLC.m3u"],
                ["Films", "http://iptviptv.do.am/_ld/0/3_Film.m3u"],
                ["Auto_IPTV", "http://getsapp.ru/IPTV/Auto_IPTV.m3u"],
                ["Auto_nogpr", "https://webarmen.com/my/iptv/auto.nogrp.m3u"],
                ["400 Chan", "https://smarttvnews.ru/apps/Channels.m3u"]]:
                try:
                    # response = urlopen()
                    response = urlopen(iptvUrl[1])
                    html = response.read().decode("utf-8")
                    name = ""
                    url = ""
                    grp = ""

                    for line in html.splitlines():
                        if line.startswith("#EXTM3U"):
                            pass # nothing to do
                        elif line.strip() == '':
                            pass # skip empty lines
                        elif line.startswith("#EXTVLCOPT:"):
                            pass # skip EXTVLCOPT
                        elif line.startswith("#EXTGRP:"):
                            grp = re.search('#EXTGRP:(.*)', line).group(1).strip()
                        elif line.startswith("#EXTINF:"):
                            name = re.search('#EXTINF:-?\d*\,?(.*)', line).group(1).strip()
                            name = re.sub(r"([a-z\-]*=\"[^\"]*\")", r"", name).strip()
                            name = re.sub(r"^(\,)", r"", name)
                        elif line.startswith("http") or line.startswith("rtmp"):
                            url = line
                            lowName = name.strip().lower()
                            self.youtubeChannels.append({\
                                "name": name,\
                                "url": url,\
                                "cat": iptvUrl[0] + ((" " + grp) if grp != "" else "")\
                            })
                            id = id + 1
                            name = ""
                        else:
                            logging.error('Unparsed string: ' + line)
                except Exception as e:
                    traceback.print_exc()
                    logging.info("FAILED TO LOAD CHANNELS:" + str(e))

            self.youtubeChannels.append({\
                    "name": 'Radio Paradise',\
                    "url": 'https://www.radioparadise.com/m3u/mp3-192.m3u',\
                    "cat": "Z: built-in"\
                })
            self.youtubeChannels.append({\
                    "name": 'Пикник на 101',\
                    "url": 'http://ic5.101.ru:8000/a157?userid=0&setst=e5l2bv8j2v1jsagt3rtc3teoq8&tok=07790631dkVJeVFPUWNKdjRGRFp2d0tySWJST3JWQy8yVnphbHVTL3R3QmJJeEZ1WjEvY3ViV3RtUjJrZ3UrVWFualdDVA%3D%3D2',\
                    "cat": "Z: built-in"\
                })
            
            # logging.info(html)

            '''
            # response = urlopen("http://acetv.org/js/data.json?0.26020398076972606").read().decode("utf-8")
            response = urlopen("http://pomoyka.win/trash/ttv-list/as.json").read().decode("utf-8")
            # logging.info(response)
            channels = json.loads(response)
            
            self.youtubeChannels = []

            for ch in channels["channels"]:
                self.youtubeChannels.append({ "name": ch["name"], "url": "http://192.168.121.38:8000/pid/" + ch["url"] + "/stream.mp4", "cat": ch["cat"] })
            '''
            self.youtubeChannels.sort(key=lambda r:nameForCompare(r))

            for ch in self.youtubeChannels:
                urlHash = bytes(hashlib.sha256(ch["url"].encode('utf-8')).digest())
                ch["id"] = urlHash.hex()
                if ch["id"] in self.youtubeChannelsByIds and self.youtubeChannelsByIds[ch["id"]]["url"] != ch["url"]:
                    logging.error("HASH CLASH: " + str(ch["id"]) + " " + ch["url"] + " " + self.youtubeChannelsByIds[ch["id"]]["url"]) 
                else:
                    self.youtubeChannelsByIds[ch["id"]] = ch
                # 
                self.youtubeChannelsByUrls[ch["url"]] = ch

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
                traceback.print_exc()
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
    def writeResult(self, res, reload=False):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\", \"reload\": " + ("true" if reload else "false") + " }").encode('utf-8'))

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

            # Server settings
            htmlContent = htmlContent.replace("/*{{{serverSettings}}}*/", json.dumps({\
                    # "sleepAt": datetime.datetime.fromtimestamp(httpd.sleepAt).isoformat(),\
                    # "wakeAt": datetime.datetime.fromtimestamp(httpd.wakeAt).isoformat(),\
                }))

            strHistory = ""
            channelsUsed = set()
            for ytb in self.server.youtubeHistory:
                if "channel" in ytb:
                    channelsUsed.add(ytb["channel"])

            for ytb in reversed(self.server.youtubeHistory):
                thisname = ytb["name"]
                if ytb["url"] in self.server.youtubeChannelsByUrls:
                    thisname = self.server.youtubeChannelsByUrls[ytb["url"]]["name"]

                encodedURL = urllib.parse.quote(ytb["url"], safe='')

                def optionText(x):
                    sel = "channel" in ytb and ytb["channel"] == x
                    return "<option value='" + str(x) + "'" +\
                                ("selected" if sel else "") + " " +\
                                ("disabled" if not sel and x in channelsUsed else "") +\
                                ">" + str(x) + "</option>"

                strHistory += "<div class='channel-line' data-cat='" + ytb["cat"] + "'>" +\
                    "<select class='channelSelect' data-url='" + encodedURL + "'>" + \
                        "<option value='0' " + ("selected" if not ("channel" in ytb) else "") + ">   </option>" +\
                        "\n".join(map(optionText, [x for x in range(10, 30)])) +\
                    "</select>" + "\n" +\
                     thisname + "&nbsp;" + \
                    "<button class='action' data-url='/tablet/youtubeURL/" \
                        + encodedURL + "'  data-uri='"\
                        + ytb["url"] + "' data-name='" + thisname + "'>[    Play    ]</button>" + "\n" +\
                    "<button class='action' data-url='/tablet/history/remove/" +\
                    encodedURL + "' >[  Remove ]</button>" + "\n"\
                    "</div>" + "\n"

            htmlContent = htmlContent.replace('<!--{{{history}}}-->', strHistory)

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
                httpd.toggleTabletPower()
            self.writeResult("OK")
        elif pathList == list(["tablet", "off"]):
            if httpd.isTabletAwake():
                httpd.toggleTabletPower()
            self.writeResult("OK")
        elif pathList == list(["tablet", "pause"]):
            httpd.playPause()
            self.writeResult("OK")
        elif pathList == list(["tablet", "onoff"]):
            httpd.toggleTabletPower()
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
        elif pathList[0] == "tablet" and pathList[1] ==  "youtubeURL":
            httpd.playYoutubeURL(urllib.parse.unquote(pathList[2]))
            self.writeResult("OK")
        elif pathList == list(["tablet", "reboot"]):
            httpd.adbShellCommand("reboot")
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "history":
            youtb = None
            if len(pathList) >= 4:
                decodedUrl = urllib.parse.unquote(pathList[3])
                youtb = next(filter(lambda ytb: ytb["url"] == decodedUrl, httpd.youtubeHistory))

            if pathList[2] == "setchannel":
                channel = int(pathList[4])
                if channel == 0:
                    del youtb["channel"]
                else:
                    youtb["channel"] = channel
            elif pathList[2] == "remove":
                decodedUrl = urllib.parse.unquote(pathList[3])
                if not ("channel" in youtb) or youtb["channel"] != 0:
                    httpd.youtubeHistory.remove(youtb)
            elif pathList[2] == "clear":
                httpd.youtubeHistory = []
            else:
                pass

            httpd.saveYoutubeHistory()
            self.writeResult("OK", True)
        elif pathList == list(["self", "reboot"]):
            subprocess.Popen("reboot", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read() # Reboot self
            self.writeResult("OK")
        elif pathList[0] == "tablet" and pathList[1] == "sleepin":
            httpd.settings["sleepAt"] = httpd.sleepAt = time.time() + int(pathList[2])
            httpd.saveSettings()

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
            httpd.settings["wakeAt"] = httpd.wakeAt
            httpd.saveSettings()
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
            milight.changeBrightness(int(pathList[2]))
            self.writeResult("OK")
        elif pathList == list(["light", "off"]):
            reportText("Выключаем свет")
            milight.off()
            self.writeResult("OK")

last = {}
prevKey = {}

def isNumKey(k):
    return len(k) == 2 and k[0] == "n" and k[1] >= '0' and k[1] <= '9'

def clockRemoteCommands(msg):
    if "type" in msg:
        if msg["type"] == "ir_key":
            now = time.time()

            # logging.info('Key: ' + msg["remote"] + ' ' + msg["key"] + ' ' + str(msg["timeseq"]))
            if not (msg["remote"] in last):
                last[msg["remote"]] = 0
            if not (msg["remote"] in prevKey):
                prevKey[msg["remote"]] = ""

            if now - last[msg["remote"]] > 0:
                k = msg["key"]

                if k == "volume_up":
                    httpd.volUp()
                elif k == "volume_down":
                    httpd.volDown()
                elif k == "channel_up" or k == "channel_down":
                    historyItem = httpd.getHistoryByUrlOrNone(httpd.nowPlayingUrl)
                    chan = 0
                    if (historyItem != None and "channel" in historyItem):
                        chan = historyItem["channel"]
                    while True:
                        chan = (chan + 100) % 100
                        if k == "channel_up":
                            chan = chan + 1
                        else:
                            chan = chan - 1
                        channelFound = httpd.getByChannelOrNone(chan)
                        if channelFound != None:
                            httpd.playOnTablet(channelFound["url"], channelFound["name"])
                            break
                elif k == "power":
                    httpd.playPause()
                elif isNumKey(k) and isNumKey(prevKey[msg["remote"]]) and (now - last[msg["remote"]] < 2):
                    # number !
                    n = int(k[1]) + 10*int(prevKey[msg["remote"]][1])
                    # logging.info("$$$>>>" + str(n))

                    ytb = httpd.getByChannelOrNone(n)
                    if ytb != None:
                        httpd.playYoutubeURL(ytb["url"])
                    else:
                        if n == 1:
                            httpd.switchRelay(relayRoom, 0)
                        elif n == 2:
                            httpd.switchRelay(relayRoom, 1)
                        elif n == 3:
                            httpd.switchRelay(relayRoom, 2)
                        elif n == 4:
                            httpd.switchRelay(relayRoom, 3)
                        elif n == 5:
                            httpd.switchRelay(relayKitchen, 0)
                        elif n == 6:
                            httpd.switchRelay(relayKitchen, 1)
                        elif n == 7:
                            if milight.on:
                                reportText("Выключаем свет")
                                milight.off()
                            else:
                                reportText("Включаем свет")
                                milight.allWhite()
                else:
                    print(msg["remote"] + " " + k)

                prevKey[msg["remote"]] = k
                last[msg["remote"]] = now
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

relayKitchen = DeviceCommunicationChannel("192.168.121.131", clockRemoteCommands, [\
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
                        httpd.toggleTabletPower()

                    httpd.settings["sleepAt"] = httpd.sleepAt = timeToSleepNever()
                    httpd.saveSettings()

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
                        httpd.toggleTabletPower()
                    ytb = httpd.getByChannelOrNone(29)
                    if ytb != None:
                        httpd.playYoutubeURL(ytb["url"])
                    httpd.settings["wakeAt"] = httpd.wakeAt = timeToSleepNever()
                    httpd.saveSettings()
            except Exception:
                traceback.print_exc()

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


