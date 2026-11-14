"""Stand-in for the realtime lobby server (TCP, boot config tcpServer/tcpPort = 127.0.0.1:18081).

The client keeps a FreeNet TCP connection to Netmarble's lobby server for presence, chat and PvP matching. Most
screens work without it (the client just retries in the background), but some flows wait for its login: the battle
tutorial only leaves for the next scene after LobbyServerPackage.OnLobbyLogin reports success (scene message 0x249).

Wire format (FreeNet.CMessageResolver): [int16 body length][int16 checksum, unchecked][body]; the client sends its
length as an int32, i.e. checksum 0. Body = protobuf NEO.C2S.Protocol.Request / Response, XORed byte by byte with a
repeating key (CUserToken.send / on_message): "preencryptedkeyy" until login, then the session key. The client puts
a random key in CQ_Login.encryptedKey; CUserToken.SetDecryptedKey makes the session key from SA_Login.encryptedKey:
byte i (16 bytes) = low byte of encryptedKey[i % len] XOR clientKeyUtf8[i % len(clientKey)]. We send back the
client's own key bytes, so the session key is 16 zero bytes and later packets travel unchanged.
  Request  {1 sequence, 2 type (MessageType), 11 cqKeepAlive, 100 cqLogin {1 accountId, 3 encryptedKey}, ...}
  Response {1 sequence, 2 type, 3 accountId, 21 saKeepAlive, 105 saServerUserConnection, 110 saLogin, ...}
What we answer: on connect SA_Server_User_Connection (success) -> the client sends Login -> SA_Login (success,
session id); KeepAlive -> SA_KeepAlive. Everything else is logged and left unanswered.
"""
import socketserver, struct, threading, time

# MessageType values (NEO.C2S.Protocol.MessageType)
KEEP_ALIVE, PING, SERVER_USER_CONNECTION, LOGIN = 1, 2, 990, 1000
NAMES = {1: "KeepAlive", 2: "Ping", 3: "PingCheck", 4: "CheckClientDisconnect", 5: "PingLatency", 6: "ClientPing",
         10: "ClientPushHomebtn", 11: "ClientReturnGamebtn", 990: "ServerUserConnection", 1000: "Login",
         1101: "ChangeUserActState", 2300: "ReconnectLobby"}
# Response field numbers of the answers we send
F_SA_PING, F_SA_KEEP_ALIVE, F_SA_SERVER_USER_CONNECTION, F_SA_LOGIN = 20, 21, 105, 110
F_CQ_LOGIN = 100            # Request.cqLogin
PRE_KEY = b"preencryptedkeyy"
SESSION_KEY = bytes(16)     # what SetDecryptedKey yields from our SA_Login.encryptedKey


def varint(n):
    out = bytearray()
    while True:
        b = n & 0x7F; n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def field_varint(num, value):
    return varint(num << 3) + varint(value)


def field_bytes(num, data):
    return varint(num << 3 | 2) + varint(len(data)) + data


def read_varint(buf, i):
    n = shift = 0
    while True:
        b = buf[i]; i += 1
        n |= (b & 0x7F) << shift; shift += 7
        if not b & 0x80:
            return n, i


def fields(buf):
    """{field number: value} of a message: ints for varints, bytes for length-delimited fields (last one wins)."""
    out, i = {}, 0
    while i < len(buf):
        key, i = read_varint(buf, i)
        num, wire = key >> 3, key & 7
        if wire == 0:
            out[num], i = read_varint(buf, i)
        elif wire == 2:
            size, i = read_varint(buf, i)
            out[num], i = buf[i:i + size], i + size
        elif wire == 1:
            i += 8
        elif wire == 5:
            i += 4
        else:
            raise ValueError(f"wire type {wire}")
    return out


def xor(data, key):
    return bytes(b ^ key[i % len(key)] for i, b in enumerate(data))


def response(seq, mtype, field, body=b""):
    return field_varint(1, seq) + field_varint(2, mtype) + field_bytes(field, body)


class LobbyHandler(socketserver.BaseRequestHandler):
    log = print
    sessions = iter(range(1, 1 << 62))

    def send(self, body):
        body = xor(body, self.key)
        self.request.sendall(struct.pack("<hh", len(body), 0) + body)

    def recv_exact(self, n):
        data = b""
        while len(data) < n:
            chunk = self.request.recv(n - len(data))
            if not chunk:
                raise ConnectionError("closed")
            data += chunk
        return data

    def login(self, seq, msg, peer):
        cq = fields(msg.get(F_CQ_LOGIN, b""))
        client_key = cq.get(3, b"").decode("utf-8", "replace")
        if not client_key:
            self.log(f"[lobby] {peer} Login without a client key; not answered")
            return
        kb = client_key.encode("utf-8")
        reply_key = "".join(chr(kb[i % len(client_key)]) for i in range(16)).encode("utf-8")
        session = next(self.sessions)
        sa = field_bytes(2, reply_key) + field_varint(3, session)
        body = response(seq, LOGIN, F_SA_LOGIN, sa)
        account = cq.get(1)
        if account:
            body += field_bytes(3, account)          # Response.accountId
        self.send(body)                               # still under the pre-shared key
        self.key = SESSION_KEY
        self.log(f"[lobby] {peer} Login -> success, session {session}")

    def handle(self):
        peer = "%s:%d" % self.client_address
        self.key = PRE_KEY
        self.log(f"[lobby] {peer} connected")
        self.send(response(0, SERVER_USER_CONNECTION, F_SA_SERVER_USER_CONNECTION))
        try:
            while True:
                length, _checksum = struct.unpack("<hh", self.recv_exact(4))
                raw = self.recv_exact(length)
                try:
                    msg = fields(xor(raw, self.key))
                except (ValueError, IndexError):
                    self.log(f"[lobby] {peer} undecodable packet ({length} bytes)")
                    continue
                seq, mtype = msg.get(1, 0), msg.get(2, 0)
                if mtype == LOGIN:
                    self.login(seq, msg, peer)
                elif mtype == KEEP_ALIVE:
                    self.send(response(seq, KEEP_ALIVE, F_SA_KEEP_ALIVE, field_varint(1, int(time.time() * 1000))))
                elif mtype == PING:
                    self.send(response(seq, PING, F_SA_PING))
                else:
                    self.log(f"[lobby] {peer} {NAMES.get(mtype, mtype)} ({length} bytes) not answered")
        except (ConnectionError, OSError) as e:
            self.log(f"[lobby] {peer} disconnected ({e})")


def start(host, port, log=print):
    LobbyHandler.log = staticmethod(log)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    server = socketserver.ThreadingTCPServer((host, port), LobbyHandler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
