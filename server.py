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
from urllib.request import urlopen

class MyServer(BaseHTTPRequestHandler):
    def _set_response(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/html')
        self.end_headers()

    youtubeChannel = 0
    youtubeChannels = []

    def adbShellCommand(self, command):
        resultStr = subprocess.Popen("adb shell " + command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stderr.read()
        if b'error: no devices/emulators found' in resultStr:
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
                        window.onload = function() {
                            Array.prototype.filter.call(document.getElementsByClassName('action'),
                                function(el) {
                                    el.addEventListener("click",
                                        function() { 
                                            var xhr = new XMLHttpRequest();
                                            xhr.open("GET", el.dataset.url, false);
                                            xhr.onload = function() {};
                                            xhr.send(); 
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
                    <button class='action' data-url='/tablet/volup'  >   + Vol +   </button>
                    <button class='action' data-url='/tablet/voldown'>   - Vol -   </button>
                </div>""".encode('utf-8'))

            strr = ""
            
            currName = None
            btns = ""
            ind = 1
            for ytb in self.youtubeChannels:
                btns += "<button class='action' data-url='/tablet/play/" + str(ytb["index"]) + "'> Play (" + str(ind) + ") </button>"
                if currName != ytb["name"] and currName != None:
                    strr += "<div>" + currName + btns + "</div>"
                    btns = ""
                    ind = 1
                else:
                    ind = ind + 1
                currName = ytb["name"]

            if len(btns) > 0:
                strr += "<div>" + currName + btns + "</div>"

            self.wfile.write(strr.encode('utf-8'))

            self.wfile.write("</body>".encode('utf-8'))
        elif pathList[0] == "init":
            self.loadM3U()
            self.send_response(200)
        elif pathList[0] == "events":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()

            self.wfile.write("[{ \"name\": \"ddd\" }]".encode('utf-8'))
        elif pathList[0] == "tablet" and pathList[1] == "play":
            self._set_response()
            self.send_header('Content-type', 'application/json')
            if (len(pathList) > 2):
                self.youtubeChannel = int(pathList[2])
            self.playCurrent()
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        elif pathList == list(["tablet", "stop"]):
            self._set_response()
            self.send_header('Content-type', 'application/json')
            self.youtubeChannel = self.youtubeChannel + 1
            self.stopCurrent()
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        elif pathList == list(["tablet", "playnext"]):
            self._set_response()
            self.send_header('Content-type', 'application/json')
            self.youtubeChannel = self.youtubeChannel + 1
            self.playCurrent()
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        elif pathList == list(["tablet", "playprev"]):
            self._set_response()
            self.youtubeChannel = self.youtubeChannel - 1
            self.playCurrent()
            self.send_header('Content-type', 'application/json')
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        elif pathList == list(["tablet", "volup"]):
            self._set_response()
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_UP")
            self.send_header('Content-type', 'application/json')
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        elif pathList == list(["tablet", "voldown"]):
            self._set_response()
            self.adbShellCommand("input keyevent KEYCODE_VOLUME_DOWN")
            self.send_header('Content-type', 'application/json')
            self.wfile.write("{ \"result\": \"OK\"}".encode('utf-8'))
        else:
            self._set_response()
            self.wfile.write("GET request for {}".format(self.path).encode('utf-8'))

    def do_POST(self):
        content_length = int(self.headers['Content-Length']) # <--- Gets the size of data
        post_data = self.rfile.read(content_length) # <--- Gets the data itself
        logging.info("POST request,\nPath: %s\nHeaders:\n%s\n\nBody:\n%s\n",
                str(self.path), str(self.headers), post_data.decode('utf-8'))

        self._set_response()
        self.wfile.write("POST request for {}".format(self.path).encode('utf-8'))

def run(server_class=HTTPServer, handler_class=MyServer, port=8000):
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


