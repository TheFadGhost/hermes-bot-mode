FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends chromium xvfb openbox x11vnc novnc websockify xdotool scrot dbus-x11 fonts-liberation tini ca-certificates && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home desktop && mkdir /profile && chown desktop:desktop /profile
COPY start.sh /usr/local/bin/start-desktop
COPY vnc_server.py /usr/local/bin/desktop-vnc.py
RUN sed -i 's/\r$//' /usr/local/bin/start-desktop && chmod 755 /usr/local/bin/start-desktop
USER 1000:1000
ENV DISPLAY=:99 HOME=/home/desktop
EXPOSE 6080
HEALTHCHECK --interval=10s --timeout=3s --start-period=20s --retries=3 CMD python3 -c "import socket; s=socket.create_connection(('127.0.0.1',5900),2); assert s.recv(12).startswith(b'RFB ')"
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/start-desktop"]
