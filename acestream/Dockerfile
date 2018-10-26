FROM resin/rpi-raspbian:jessie
RUN apt-get update -y
RUN DEBIAN_FRONTEND=noninteractive apt-get install -y wget  unzip ca-certificates
RUN adduser --disabled-password --gecos "" tv
RUN cd / && wget https://github.com/sshmanko/acestream-armv7/archive/v3.1.24.tar.gz -O acestream_rpi.tar.gz && tar xfv acestream_rpi.tar.gz
EXPOSE 62062
EXPOSE 6000:8000
# ENTRYPOINT ["/acestream/start_acestream.sh"]
ENTRYPOINT ["/bin/bash"]