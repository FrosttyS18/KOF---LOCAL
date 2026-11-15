"""Local stand-in server for the KOF ALLSTAR PC client.

The patched client sends every Netmarble URL here as  http://127.0.0.1:18080/<original-host>/<path>.
Run:  python kofserver.py
"""
import hashlib, json, os, re, sys, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kofcrypto
import gameapi
import lobbytcp

HOST, PORT = "127.0.0.1", 18080
TCP_PORT = 18081  # realtime lobby server (lobbytcp.py)
BASE = f"http://{HOST}:{PORT}"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG = open(os.path.join(LOG_DIR, time.strftime("requests-%Y%m%d-%H%M%S.log")), "a", encoding="utf-8")

# cipher keys we know of; session keys get added once we hand them out
KEYS = {"pcauth": kofcrypto.PCAUTH_KEY}


def log(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    LOG.write(line + "\n"); LOG.flush()


def boot_config(version):
    """config_{appVersion}_win.json: AES(base64) JSON read by ServerSelect / NetworkManagerWEB."""
    server = {
        "webServer": f"{BASE}/game/",
        "cdnServer": f"{BASE}/cdn/",
        "tableDataServer": f"{BASE}/table/",
        "tcpServer": HOST, "tcpPort": str(TCP_PORT),
        # RegionSelector.RegionServerInfo.SetServerInfo, one entry per realtime (PvP/guild) region
        "tcpServer_multi": [{
            "tcpServer": HOST, "tcpPort": str(TCP_PORT), "stringkey": "local",
            "serverID": "1", "serverIDs": ["1"], "preferredRegionCode": ["ALL"], "CityCodes": {},
        }],
        "sdkZone": "real",
        "UseProtoToJSON": "y",
        "cdnVersion": "700",  # = AssetbundleVersion stored in kofallstar.prefs
        "notice": "n", "goodReview": "n", "coupon": "n", "guide": "n", "fakeAd": "n", "eula": "n",
        "streaming": "n", "guildChat": "n", "performanceSelect": "n", "useLog": "n",
        "guestChannel": "y", "facebookSignInDisable": "y", "useIAPResultLog": "n",
        "tutorialMovieSkip": "y", "battleTutorialSkip": "y",   # "y": END TUTORIAL button in the battle tutorial
        "activeFullDownloadOnTitle": "n", "activeFullDownloadAtCheckBundles": "n", "activeFullDownloadOnly": "n",
        "activeSpecialRewardButton": "n", "firstForumView": "n", "firstPromotionViewLoc": "0",
        "inputKeyUseSimpleData": "n", "inputKeyNoDuplicateSend": "n", "inputKeyUseDelay": "n",
        "inputKeyReconnect": "n",
    }
    cfg = {
        "target": "prod",  # must equal SelectedServer in kofallstar.prefs, or the client wipes tablepacks.info
        "prod": server,
        "serverCheckYn": "n", "serverMessage": "",
        "minVersion": version, "newVersion": version, "minVersionMessage": "", "newVersionMessage": "",
        "marketPath": "", "agreeUrl1": "", "agreeUrl2": "", "agreeUrl3": "", "shopUrl1": "", "shopUrl2": "",
        "pcplayGuideUrl": "",
        # UIView_TitleAnimation: default ResourcesAssets/UI/UI_Title_KOF2002 no longer exists in resourcesassets_ui;
        # title screens live in per-prefab bundles (prefabs_ui_data_ui_unit_title_ui_title_*)
        "titlePrefabPath": "Prefabs/UI_Data/UI_Unit/Title/UI_Title_KOF2002",
        "downloaderRetryMax": "3", "downloaderTimeout": "30", "downloadThreadMax": "4",
        "downloadAutoRetrySeconds": "5", "checkedTableFileExists": "n", "tableFileExistsList": "",
        "waitForSignIn": "0", "lowDevice": "", "lowRes": "0",
        "maintenanceStartTime": "", "maintenanceEndTime": "", "maintenanceTimeFormat": "",
    }
    # RecvSecuredServerInfo may read globals from the selected server node; provide them in both places
    for k, v in list(cfg.items()):
        if k not in ("target", "prod"):
            server.setdefault(k, v)
    return cfg


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    def _reply(self, code, body=b"", ctype="application/json", headers=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        path = urlsplit(self.path).path
        log(f"\n>> {self.command} {self.path}")
        for k, v in self.headers.items():
            log(f"   {k}: {v}")
        if body:
            how, plain = kofcrypto.try_decode(body, KEYS)
            log(f"   body[{len(body)}] ({how}): {plain[:4000]!r}")

        for rx, fn in ROUTES:
            m = re.match(rx, path)
            if m:
                code, out, ctype = fn(self, m, body)
                log(f"<< {code} {ctype} {out[:300]!r}")
                return self._reply(code, out, ctype)

        log("<< 404 (unhandled)")
        self._reply(404, b"{}")

    do_GET = do_POST = do_PUT = _handle


TABLE_PACK_VERSION = 1020  # must match tools/make_tablepacks.py


def r_config(req, m, body):
    cfg = json.dumps(boot_config(m.group(1))).encode()
    return 200, kofcrypto.encrypt_b64(cfg, kofcrypto.CONFIG_KEY), "text/plain"


def r_table_version(req, m, body):
    # DownloadManager.RecvDownloadTableVersion reads ["table"] and ["lang_global"]
    v = TABLE_PACK_VERSION
    return 200, json.dumps({"table": v, "lang_global": v, "prohibited": v}).encode(), "application/json"


# ---------------------------------------------------------------- Netmarble SDK (the Android client)
# The Android client signs in through Netmarble's Java SDK 4.9, whose URLs tools/android_apk.py points here. Its v4
# constants (PlatformDetails.getGMC2Constants: errorCode, resultData {checksum, geolocation, clientIp, geoIp, constants})
# must hold every URL com.netmarble.network.SessionNetwork.checkConstants requires; Netmarble's own server has answered
# with empty constants since the end of service (tmp/netmarble_ref). All of them are ours, so each SDK service lands here
# as /apis.netmarble.com/<its path>. The guest sign-in ({authUrl}/mobileauth/v2/players/{playerID}/deviceKeys/
# {deviceKey}/accessToken; com.netmarble.core.SessionImpl$10) reads resultData.accessToken (-> the game token),
# resultData.player (gameRegion, joinedCountryCode) and resultData.cipherKeyList - the keys the game encrypts its
# requests with - so it gets the session the PC's session/pcAuth hands out (gameapi), whose keys the server reads.
NM_BASE = f"{BASE}/apis.netmarble.com"
NM_URLS = ("attributionUrl", "applicationSignUrl", "authUrl", "consultUrl", "couponUrl", "gameInfoUrl", "loginUrl",
           "logUrl", "marblePopUrl", "noticeUrl", "pushUrl", "reviewInfoUrl", "reviewUrl", "webviewUrl", "cafeUrl",
           "latencyUrl", "columbusPushUrl", "eventCalendarUrl")
NM_GEO = {"geolocation": "US", "clientIp": "127.0.0.1",
          "geoIp": {"isoCountry": "US", "isoCity": "", "cityName": "", "countryName": "United States"}}


def nm_ok(result):
    return 200, json.dumps({"errorCode": 0, "errorMessage": "success", "resultData": result}).encode(), "application/json"


def r_nm_constants(req, m, body):
    constants = {k: NM_BASE for k in NM_URLS} if m.group(1) == "netmarbles" else {}
    checksum = hashlib.sha256(json.dumps(constants, sort_keys=True).encode()).hexdigest().upper()
    return nm_ok({"checksum": checksum, **NM_GEO, "constants": constants})


def r_nm_sign_in(req, m, body):
    player = {"playerId": m.group(1), "deviceKey": m.group(2), "gameCode": "kofg", "gameRegion": "global",
              "joinedCountryCode": "US"}
    return nm_ok({"accessToken": "offline-" + m.group(1), "player": player, "cipherKeyList": [
        {"cipherType": "CIPHER_AES_128_CBC", "secretKey": gameapi.SESSION_AES_KEY_HEX,
         "aesInitVec": gameapi.SESSION_AES_IV_HEX},
        {"cipherType": "CIPHER_RC4_40", "secretKey": gameapi.SESSION_RC4_KEY_HEX}]})


CACHE = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "storage", "cache"))


def zip_folder(folder):
    """Table packs are zips that DownloadManager.ExtractTableEntry unpacks into the pack folder.
    We rebuild them from the client's own cached files."""
    import io, zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED if os.path.basename(folder) == "banner" else zipfile.ZIP_DEFLATED) as z:
        for f in sorted(os.listdir(folder)):
            z.write(os.path.join(folder, f), f)
    return buf.getvalue()


_zip_cache = {}


def r_table_zip(sub):
    def handler(req, m, body):
        folder = os.path.join(CACHE, sub)
        if not os.path.isdir(folder):
            return 404, b"", "application/octet-stream"
        if folder not in _zip_cache:
            _zip_cache[folder] = zip_folder(folder)
        return 200, _zip_cache[folder], "application/octet-stream"
    return handler


def r_banner_version(req, m, body):
    # DownloadManager.RecvDownloadBannerVersion reads ["banner_" + LanguageManager.GetActivedLanguageName()]
    v = TABLE_PACK_VERSION
    langs = ("en", "EN", "English", "english", "ko", "ja", "zh", "tw", "th", "es", "pt", "id", "fr", "de", "global")
    return 200, json.dumps({f"banner_{l}": v for l in langs}).encode(), "application/json"


BUNDLES = os.path.join(CACHE, "assetbundles")
_manifests = {}


def bundle_source(platform):
    """(assetbundles.info, bundle name -> its file) of a platform's cached bundles, or (None, None): "win" the PC cache
    (files named md5(bundle name)); "aos" the Android app's files folder copied to this PC (server/state/options.json
    "androidFiles"; files under their own names, the "android" manifest bundle among them)"""
    import hashlib
    if platform == "aos":
        root = gameapi.server_options().get("androidFiles")
        if not root:
            return None, None
        return os.path.join(root, "assetbundles.info"), lambda name: os.path.join(root, "assetbundles", name)
    return os.path.join(CACHE, "assetbundles.info"), lambda name: os.path.join(BUNDLES, hashlib.md5(name.encode()).hexdigest())


def bundle_manifest(platform):
    """'name:hash:size' per line (AssetBundleManager.ParseBundleInfo), from the client's own index
    (assetbundles.info) so every cached bundle matches"""
    if platform not in _manifests:
        import struct
        index, file_of = bundle_source(platform)
        d = open(index, "rb").read()
        i, lines = 0, []
        while i + 4 <= len(d):
            n = struct.unpack_from("<i", d, i)[0]; name = d[i + 4:i + 4 + n].decode(); i += 4 + n
            n = struct.unpack_from("<i", d, i)[0]; val = d[i + 4:i + 4 + n].decode(); i += 4 + n
            if len(val) != 32:
                continue  # e.g. $EmbedBundleVersion
            f = file_of(name)
            if not os.path.exists(f):
                continue  # don't advertise a bundle we have no file for: the dead CDN would 404 and the client fails
            lines.append(f"{name}:{val}:{os.path.getsize(f)}")
        _manifests[platform] = ("\n".join(lines) + "\n").encode()
        log(f"   built {platform} bundle manifest: {len(lines)} bundles")
    return _manifests[platform]


def r_cdn(platform):
    def handler(req, m, body):
        from urllib.parse import unquote
        name = unquote(m.group(1))
        index, file_of = bundle_source(platform)
        if index is None or os.path.basename(name) != name or name in ("", ".", ".."):
            return 404, b"", "application/octet-stream"
        if name == "fullbundles.snapshot" and platform == "aos":
            return 200, b"\n", "text/plain"   # aos only: the source data lacks the bulk-download fullbundles_N.zip, so
            # the game must not try to fetch them off the dead CDN; the per-bundle manifest lists every present bundle.
            # win keeps returning the manifest (its data is complete, has no fullbundles entries - proven on PC).
        if name in ("bundle.manifest", "fullbundles.snapshot") or name.endswith(".lst"):
            return 200, bundle_manifest(platform), "text/plain"
        f = file_of(name)
        if os.path.exists(f):
            return 200, open(f, "rb").read(), "application/octet-stream"
        return 404, b"", "application/octet-stream"
    return handler




TABLE_HASHES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tables", "hashes.json")


def r_table_hashes(pack):
    """{0}/common/table/*.kof: AES(JSON [{name, hash}]) with the session table key (SceneLogin.SetHashToTable).
    Only tables we rebuilt (tools/build_tables.py -> tables/hashes.json) are listed: a listed table is
    decrypted with our key; an unlisted one keeps m_encrypted=false and a null hash, so BaseTable.LoadTable
    reads nothing and the table stays empty (no error)."""
    def handler(req, m, body):
        try:
            entries = json.load(open(TABLE_HASHES, encoding="utf-8")).get(pack, {})
        except FileNotFoundError:
            entries = {}
        data, loc = gameapi.table_keys()
        k = loc if pack == "lang" else data
        plain = json.dumps([{"name": n, "hash": h} for n, h in sorted(entries.items())]).encode()
        log(f"   {pack} hash list: {len(entries)} tables")
        return 200, kofcrypto.encrypt(plain, (bytes.fromhex(k["key"]), bytes.fromhex(k["iv"]))), "application/octet-stream"
    return handler


UNHANDLED = set()


def r_game(req, m, body):
    """/game/<api>: decode the (encrypted) JSON request and dispatch to gameapi."""
    name = m.group(1)
    how, plain = kofcrypto.try_decode(body, KEYS)
    try:
        req_json = json.loads(plain.decode("utf-8")) if plain else {}
    except Exception:
        req_json = {"_raw": plain[:200].decode("latin-1")}
    out, handled, cls = gameapi.handle(name, req_json)
    if not handled:
        UNHANDLED.add(name)
        log(f"   !! no handler for {name}; default {cls or 'success'} response")
    return 200, json.dumps(out).encode(), "application/json"


ROUTES = [
    (r"^/game/(.+)$", r_game),
    (r"^/table/common/table/table\.kof$", r_table_hashes("common")),
    (r"^/table/common/table/lang_(\w+)\.kof$", r_table_hashes("lang")),
    (r"^/table/common/table/prohibited_\w+?_text_words\.kof$", r_table_hashes("prohibited")),
    (r"^/cdn/assets/win/r\d+/dxt/(.+)$", r_cdn("win")),
    (r"^/cdn/assets/aos/r\d+/astc/(.+)$", r_cdn("aos")),          # the Android client (adb reverse tcp:18080)
    (r"^/apis\.netmarble\.com/gmc2/v4/constants/(\w+)/versions/[^/]+$", r_nm_constants),     # its Netmarble SDK
    (r"^/apis\.netmarble\.com/mobileauth/v2/players/([^/]+)/deviceKeys/([^/]+)/accessToken$", r_nm_sign_in),
    (r"^/apis\.netmarble\.com/push/channels$", lambda req, m, body: nm_ok({})),
    (r"^/netmarbleslog\.netmarble\.com/", lambda req, m, body: (200, b"{}", "application/json")),
    (r"^/kofg\.gcdn\.netmarble\.com/kofg/config/config_(.+)_(?:win|aos)\.json$", r_config),   # PC, Android
    (r"^/table/common/table/version\.kof$", r_table_version),
    (r"^/table/common/table/table\.dat$", r_table_zip("table/offline_common")),
    (r"^/table/common/table/prohibited_\w+?_text_words\.dat$", r_table_zip("table/prohibited")),
    (r"^/table/common/table/lang_(\w+)\.dat$", lambda req, m, body: r_table_zip("table/offline_lang_" + m.group(1))(req, m, body)),
    (r"^/table/common/banner/version\.kof$", r_banner_version),
    (r"^/table/common/banner/[^/]+\.dat$", r_table_zip("banner")),
]


if __name__ == "__main__":
    log(f"KOF ALLSTAR local server on {BASE}, lobby TCP on {HOST}:{TCP_PORT}")
    lobbytcp.start(HOST, TCP_PORT, log)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
