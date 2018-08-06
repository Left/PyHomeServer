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
import socket
from urllib.request import urlopen
from socketserver import ThreadingMixIn

class HomeHTTPHandler(BaseHTTPRequestHandler):
    youtubeChannel = 0
    youtubeChannels = []

    def writeResult(self, res):
        self.send_response(200)
        self.send_header('Content-type', 'application/json;charset=utf-8')
        self.end_headers()
        self.wfile.write(("{ \"result\": \"" + res + "\"}").encode('utf-8'))

    def adbShellCommand(self, command):
        resultStr = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read()
        if len(resultStr) > 0:
            subprocess.Popen("adb connect 192.168.121.166:5556", shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()
            # And try again
            subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.read()


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
        html = response.read().decode("utf-8")
        name = ""
        url = ""

        self.youtubeChannels = []
        for line in html.split("\r\n"):
            if line.startswith("#EXTINF"):
                name = re.search('#EXTINF:-?\d*\,(.*)', line).group(1).strip()
            elif line.startswith("http"):
                url = line
                self.youtubeChannels.append({ "name": name, "url": url })
                name = ""
       
        self.youtubeChannels.sort(key=lambda r:r["name"])
        ind = 0
        for ch in self.youtubeChannels:
            ch["index"] = ind
            ind = ind + 1
 
    def do_GET(self):
        logging.info("GET request,\nPath: %s\nHeaders:\n%s\n", str(self.path), str(self.headers))
        pathList = list(filter(None, self.path.split("/")))
        
        if len(pathList) == 0:
            self.loadM3U()

            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()

            self.wfile.write("""
                <head>
                    <meta http-equiv=\"content-type\" content=\"text/html; charset=UTF-8\">
                    <script type="text/javascript">
                        function sendReq(url) {
                            var xhr = new XMLHttpRequest();
                            xhr.open("POST", url, false);
                            xhr.onload = function() {};
                            xhr.send(); 
                        }

                        window.onload = function() {
                            document.getElementById('birghtness').addEventListener('input', 
                                function(e) {
                                    console.log('BRIGHT', e.srcElement.value);
                                    sendReq("/light/brightness/" + e.srcElement.value);
                                }, false);

                            Array.prototype.filter.call(document.getElementsByClassName('action'),
                                function(el) {
                                    el.addEventListener("click",
                                        function() { 
                                            sendReq(el.dataset.url);
                                        },
                                        false
                                    );
                                }
                            );
                        }
                    </script>
                </head>""".encode('utf-8'))
            self.wfile.write("<body>".encode('utf-8'))
            self.wfile.write("""
                <div>
                    <button class='action' data-url='/tablet/onoff'  >    POWER    </button>
                    <button class='action' data-url='/tablet/volup'  >   + Vol +   </button>
                    <button class='action' data-url='/tablet/voldown'>   - Vol -   </button>
                    <button class='action' data-url='/tablet/stop'   >     STOP    </button>
                    <button class='action' data-url='/tablet/reboot' >    REBOOT   </button>
                    <button class='action' data-url='/light/on     ' > LIGHT ON </button>
                    <button class='action' data-url='/light/off    ' > LIGHT OFF </button>
                    <input type="range" id="birghtness" name="birghtness" min="0" max="100" />
                </div>""".encode('utf-8'))

            strr = ""
            
            currName = None
            btns = ""
            ind = 1
            for ytb in self.youtubeChannels:
                btns += "<button class='action' data-url='/tablet/play/" + str(ytb["index"]) + "'> Play (" + str(ind) + ") </button>"
                if currName != ytb["name"] and currName != None:
                    strr += "<div>" + currName + "&nbsp;" + btns + "</div>"
                    btns = ""
                    ind = 1
                else:
                    ind = ind + 1
                currName = ytb["name"]

            if len(btns) > 0:
                strr += "<div>" + currName + btns + "</div>"

            self.wfile.write(strr.encode('utf-8'))

            self.wfile.write("</body>".encode('utf-8'))
        else:
            self.writeResult("UNKNOWN CMD {}".format(self.path))

    def do_POST(self):
        pathList = list(filter(None, self.path.split("/")))
        if pathList[0] == "init":
            self.loadM3U()
            self.send_response(200)
        elif pathList[0] == "tablet" and pathList[1] == "play":
            if (len(pathList) > 2):
                self.youtubeChannel = int(pathList[2])
            self.playCurrent()
            self.writeResult("OK")
        elif pathList == list(["tablet", "stop"]):
            self.youtubeChannel = self.youtubeChannel + 1
            self.stopCurrent()
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
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_UP")
            self.writeResult("OK")
        elif pathList == list(["tablet", "voldown"]):
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_DOWN")
            self.writeResult("OK")
        elif pathList == list(["tablet", "onoff"]):
            self.adbShellCommand("input keyevent KEYCODE_POWER")
            self.writeResult("OK")
        elif pathList == list(["tablet", "reboot"]):
            self.adbShellCommand("reboot")
            self.writeResult("OK")
        elif pathList == list(["light", "on"]):
            self.milightCommand(b'\xc2\x00\x55') # all white
            self.writeResult("OK")
        elif pathList[0] == "light" and pathList[1] == "brightness":
            # passed brightness is in format 0..100
            ba = bytearray(b'\x4E\x00\x55')
            ba[1] = int(0x2 + (0x15 * int(pathList[2]) / 100))
            self.milightCommand(bytes(ba)) # 
            self.writeResult("OK")
        elif pathList == list(["light", "low"]):
            self.milightCommand(b'\x45\x02\x55')
            self.writeResult("OK")
        elif pathList == list(["light", "off"]):
            self.milightCommand(b'\x46\x00\x55')
            self.writeResult("OK")
        
        
class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    pass


def run(server_class=ThreadingSimpleServer, handler_class=HomeHTTPHandler, port=8000):
    logging.basicConfig(level=logging.INFO)
    server_address = ('', port)

    httpd = server_class(server_address, handler_class)
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


