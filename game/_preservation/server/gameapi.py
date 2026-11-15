"""Game API (webServer = /game/). Requests are Newtonsoft JSON of NEO.Kof.Api.Protocol classes, AES-CBC +
base64 (+gzip when large). We answer plain 'application/json' (NetworkRequest.HandleJsonPlain), with the
WEBResponseBase fields (ResultCode, ResultMessage) plus the response class's fields (C# field names).

Player state lives in state/save.json (created by session/create)."""
import base64, json, os, random, threading, time

import apidefaults
import kofcrypto

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.abspath(os.path.join(HERE, "..", "..", "storage", "cache"))
SAVE = os.path.join(HERE, "state", "save.json")

# Cipher handed to the client in the session (NMRestApi.Session.cipherDataDict); requests after pcAuth use it.
# Same bytes as the hardcoded pcAuth cipher keeps decoding simple.
SESSION_AES_KEY_HEX = "CA4BB353B60D4F10321ED79DB1B7A2F1"
SESSION_AES_IV_HEX = "CD2F0231A8D43378FF29C26D95E3B6AB"
SESSION_RC4_KEY_HEX = "4B4F464153"

APIS = {}
_lock = threading.Lock()


def api(name):
    def deco(fn):
        APIS[name] = fn
        return fn
    return deco


def now_ms():
    return int(time.time() * 1000)


def read_prefs():
    """NMRestApi.PlayerPrefs file (storage/cache/kofallstar.prefs): base64(AES-CBC(JSON))."""
    try:
        raw = open(os.path.join(CACHE, "kofallstar.prefs"), "rb").read()
        key = (b"KoFallStaR!@PC#$", b"PC%^wInDoWsPrEfs")
        return json.loads(kofcrypto.decrypt(base64.b64decode(raw), key))
    except Exception:
        return {}


PREFS = read_prefs()
# Session ctor wipes all prefs when playerId differs from the saved kNMPlayerID, so reuse it.
PLAYER_ID = PREFS.get("kNMPlayerID") or "00000000000000000000000000000001"
DEVICE_KEY = PREFS.get("kNMDeviceKey") or "00000000000000000000000000000002"
USN = 1


# ---------------------------------------------------------------- player state
def load_state():
    try:
        return json.load(open(SAVE, encoding="utf-8"))
    except FileNotFoundError:
        return None


def save_state(state):
    os.makedirs(os.path.dirname(SAVE), exist_ok=True)
    tmp = SAVE + ".tmp"
    json.dump(state, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, SAVE)


# Starting resources for a new offline account (kept in save.json; edit there to change). AP 90 = the rank-1 max.
START_MONEY = {"ActivePoint": 90, "ActivePointMax": 90, "Gold": 1000000, "Cash": 1000, "FriendPoint": 0}
# AP comes back one point every AP_SECONDS below the max (ConfigTable 105, ConfigType AccountActivePointUpdateTime,
# which the top bar counts down before it asks player/activePointGive); the interval is ours.
AP_SECONDS = 120     # one AP every 2 minutes (gen_story.AP_REGAIN_SECONDS, the fan guide)


def route(state):
    return apidefaults.default(
        "Route", Pid=PLAYER_ID, Usn=USN, GameDb=1, CountryCode="US", RegionCode="global",
        NickName=state["nickname"], FirstConnectDatetime=state["created"],
        LastConnectDatetime=now_ms(), AccountId="offline")


def character(c, start=None):
    """Character (owned fighter) from its saved progress; never below the fighter's start grade (its rarity).
    Ex is 1 for a changed-up fighter and for every EX-frame one: the client counts a fighter as EX only by this flag
    (CharacterData.Character.get_IsEx: the EX core board's tiers, its EX skill)."""
    grade = max(c.get("grade", 3), (start or {}).get(c["index"], 0))
    ex = 1 if c.get("ex") or c["index"] in ex_tables()[2] else 0
    return apidefaults.default(
        "Character", CharacterIndex=c["index"], Grade=grade, Exp=c.get("exp", 0),
        CreateTime=c.get("created", now_ms()), LimitBreakGrade=c.get("limitBreakGrade", 0),
        LimitBreakProgressCount=c.get("limitBreakProgress", 0), EnchantHp=c.get("enchantHp", 0),
        EnchantAtk=c.get("enchantAtk", 0), EnchantDef=c.get("enchantDef", 0), Ex=ex, ex=ex,
        AffectionExp=c.get("affection", 0), Awaken=c.get("awaken", 0), AwakenExp=c.get("awakenExp", 0),
        corePoint=ex_core_points(c),
        **{f"BattleCardNo{i}": no for i, no in enumerate(c.get("battleCards", []), 1)},
        **{f"{case}mprintStoneNo{i}": no for i, no in enumerate(c.get("stones", []), 1) for case in ("I", "i")})


TABLES = os.path.join(HERE, "tables", "data")


def table_rows(name):
    try:
        return json.load(open(os.path.join(TABLES, name + ".json"), encoding="utf-8"))["rows"]
    except FileNotFoundError:
        return []


def start_grades():
    return {r["characterIndex"]: r.get("characterStartGrade", 3) for r in table_rows("CharacterTable")}


# The Prove Dungeon's bosses are real CharacterTable fighters the client's duel path needs
# (Model_ProveDungeon.SetBossCharacters resolves ProveDungeonBossTeamTable's bossTeamStringIndex and
# bossTeamStrikerIndex there), but they are not collectible: while save.json carries "ownAllFighters"
# they must not become owned fighters, fighter-memory drops, gacha frame entries or owns() hits (loading
# their prefabs from the roster could even ask for a bundle the cache lacks). The set is derived from the
# boss-team table itself -- never from name tags -- so a row keeps its NPC status by data, and every
# playable fighter stays untouched. Lookups the bosses themselves need (by index: leveling, growth,
# character_state) keep reading the whole table.
_npc_cache = {}


def npc_fighter_indexes():
    """CharacterIndex set of the Prove boss/striker fighters, cached per ProveDungeonBossTeamTable mtime."""
    f = os.path.join(TABLES, "ProveDungeonBossTeamTable.json")
    key = os.path.getmtime(f) if os.path.exists(f) else 0
    if _npc_cache.get("key") != key:
        _npc_cache.update(key=key, data={int(r[k]) for r in table_rows("ProveDungeonBossTeamTable")
                                         for k in ("bossTeamStringIndex", "bossTeamStrikerIndex") if r.get(k)})
    return _npc_cache["data"]


def player_character_rows():
    """CharacterTable rows minus the Prove NPC fighters: the roster/memory/gacha view of the table."""
    npc = npc_fighter_indexes()
    return [r for r in table_rows("CharacterTable") if r["characterIndex"] not in npc]


def owned_characters(state):
    """The saved fighters, plus every player fighter of our CharacterTable (tools/gen_roster.py) at its start
    grade while save.json has "ownAllFighters": true (the default; set it to false to keep only what the
    account earned). The Prove NPC bosses are never auto-owned (player_character_rows)."""
    chars = list(state["characters"])
    if state.get("ownAllFighters", True):
        have = {c["index"] for c in chars}
        chars += [{"index": r["characterIndex"], "grade": r.get("characterStartGrade", 3), "exp": 0,
                   "created": state["created"]} for r in player_character_rows() if r["characterIndex"] not in have]
    if state.get("unlimited"):
        max_levels(chars)
    return chars


# Test players' fighters (save.json "unlimited") are at their star grade's max level (ConfigTable 1101-1104 =
# tools/gen_growth.MAX_LEVEL: 30 at 3* .. 60 at 6*; lower grades 3*'s), so a test team is far above every stage's
# RECOMMENDED and AUTO can clear runs. The fighter list comes with the sign-in replies: levels show after a restart.
MAX_LEVEL_CONFIG = {3: 1101, 4: 1102, 5: 1103, 6: 1104}


def max_levels(chars):
    """Raise each fighter's exp to the start of its grade's max level (fighter_level: level L from the end of L-1)."""
    config = {r["configIndex"]: r.get("value1") for r in table_rows("ConfigTable")}
    ends = {r["chracterLevel"]: r for r in table_rows("CharacterLevelingTable")}
    kinds = {r["characterIndex"]: (r.get("levelingType", 1), r.get("characterStartGrade", 3))
             for r in table_rows("CharacterTable")}
    for c in chars:
        kind, start = kinds.get(c["index"], (1, 3))
        top = int(config.get(MAX_LEVEL_CONFIG.get(max(int(c.get("grade", 3)), start), 1101)) or 30)
        c["exp"] = max(int(c.get("exp", 0)), ends.get(top - 1, {}).get(f"exp{kind}", 0))


def character_state(state, index):
    """The saved progress entry of a fighter, created (at its start grade) the first time it changes."""
    for c in state["characters"]:
        if c["index"] == index:
            c["grade"] = max(c.get("grade", 3), start_grades().get(index, 0))  # saved before rarities existed
            return c
    c = {"index": index, "grade": start_grades().get(index, 3), "exp": 0, "created": now_ms()}
    state["characters"].append(c)
    return c


# Offline starting inventory (save.json "items" once it exists): EXP capsules and every fighter's soul, so
# levelling, evolving and limit breaking can be used right away. Item numbers: tools/gen_growth.py.
START_ITEMS = {str(i): 999 for i in (1000, 1001, 1002, 1003, 1093, 1094, 1095)}
START_SOULS = 99
# items every account keeps (older saves get them too): the Power Up Dungeon's key, which the EXP screen looks up in
# the inventory (tools/gen_growth.DUNGEON_KEYS); nothing uses it up offline yet
ALWAYS_ITEMS = {"1301": 5}
# items given once to every account (save.json "grants" records it): 30 AUTO-CLEAR TICKETs (video 4's QUEST INFO
# showed x30; video 5 x40 after +10 from the check-in mail) and 12 tickets of each roulette (video 5: OWNED 12)
ONCE_ITEMS = {"1302": 30, "1321": 12, "1324": 12, "210100": 5}   # + 5 EX core reset tickets (ours)
# Memories (ItemType 50, tools/gen_growth.py), given once as well (grant "memories2"; ours - the real game paid them
# for duplicate summons, event shops and boxes, none of which exist offline): every fighter's own memory x 13 (its
# A1-A5 take 7, Change Up 3), every prime memory x 6 (A6-A9) and every generic memory x 99
MEMORY_GRANT_OWN, MEMORY_GRANT_PRIME, MEMORY_GRANT_GENERIC = 13, 4, 99   # prime: A6-A9 one each (REAL)
MEMORY_GRANT = "memories2"
# Test players (save.json "unlimited": true): every read of the wallet or the inventory tops these up again, so a
# test never runs out of AP, gold, rubies, the other currencies or any item (all of ItemTable, 999 each).
# tools/account.py unlimited on|off sets it; the saved test accounts have it, and accounts made after
# tools/new_game.py get it (options.json "unlimitedNewAccounts"; new_game.py --normal: not).
UNLIMITED_MONEY = {"ActivePoint": 999, "Gold": 99_999_999, "Cash": 999_999, "FriendPoint": 10_000,   # its cap
                   "SoulToken": 999_999, "ColosseumCoin": 999_999, "ColosseumTicket": 999, "Topaz": 999_999,
                   "SoulDust": 999_999, "ArenaLeagueCoin": 999_999, "ArenaLeagueTicket": 999, "GuildCoin": 999_999}
UNLIMITED_ITEMS = 999


def items(state):
    if "items" not in state:
        inv = dict(START_ITEMS)
        for r in table_rows("ItemTable"):
            if r.get("itemType") == 5 and r.get("characterIndex"):
                inv[str(r["itemIndex"])] = START_SOULS
        state["items"] = inv
    for k, n in ALWAYS_ITEMS.items():
        if int(state["items"].get(k, 0)) <= 0:
            state["items"][k] = n
    granted = state.setdefault("grants", [])
    for k, n in ONCE_ITEMS.items():
        if k not in granted:
            state["items"][k] = int(state["items"].get(k, 0)) + n
            granted.append(k)
    if MEMORY_GRANT not in granted:
        memories = [r for r in table_rows("ItemTable") if r.get("itemType") == 50]
        for r in memories:
            k = str(r["itemIndex"])
            n = MEMORY_GRANT_GENERIC if not r.get("characterIndex") else \
                MEMORY_GRANT_OWN if not r.get("itemSubType") else MEMORY_GRANT_PRIME
            state["items"][k] = int(state["items"].get(k, 0)) + n
        if memories:
            granted.append(MEMORY_GRANT)
    if state.get("unlimited"):
        inv = state["items"]
        for k in {str(r["itemIndex"]) for r in table_rows("ItemTable")} | set(inv):
            inv[k] = max(int(inv.get(k, 0)), UNLIMITED_ITEMS)
    return state["items"]


def item_list(state, only=None):
    inv = items(state)
    keys = inv if only is None else [str(k) for k in only]
    # the protocol Item has just these fields (api_types' "Item" is merged with a UI class of the same name)
    return [{"ItemIndex": int(k), "Qty": max(0, int(inv.get(k, 0))), "Lock": 0, "UpdateTime": now_ms()} for k in keys]


def use_items(state, item_reqs):
    """Take the items a request used ({ItemIndex, Qty}: Qty = how many were used)."""
    inv = items(state)
    used = []
    for it in item_reqs or []:
        k = str(it.get("ItemIndex", 0))
        n = int(it.get("Qty", 0))
        if k != "0" and n > 0:
            inv[k] = max(0, int(inv.get(k, 0)) - n)
            used.append(k)
    return used


def ap_max(exp):
    """Max AP by account rank, sent in every AccountMoney (the client keeps no table for it): 90 at rank 1 and 92
    at rank 2 in the 2023 videos; +2 a rank after that is ours."""
    return 88 + 2 * account_level(exp)


def regen_ap(state):
    """Add the AP regained since the last update (state["apTime"], ms) up to the max; AP above the max (rank-up
    refills, potions) stays. Returns the wallet."""
    wallet = state.setdefault("money", dict(START_MONEY))
    top, now = ap_max(state.get("exp", 0)), now_ms()
    since = state.get("apTime") or now
    ap = int(wallet.get("ActivePoint", 0))
    if ap >= top:
        since = now
    else:
        gained = (now - since) // (AP_SECONDS * 1000)
        ap, since = min(top, ap + gained), (now if ap + gained >= top else since + gained * AP_SECONDS * 1000)
    wallet["ActivePoint"], state["apTime"] = ap, since
    if state.get("unlimited"):
        wallet.update(UNLIMITED_MONEY)
    return wallet


def spend_ap(state, n):
    wallet = regen_ap(state)
    full = wallet["ActivePoint"] >= ap_max(state.get("exp", 0))
    wallet["ActivePoint"] = max(0, wallet["ActivePoint"] - max(0, n))
    if full:
        state["apTime"] = now_ms()      # the regen clock starts when AP drops below the max


def money(state):
    m = dict(START_MONEY)
    m.update(regen_ap(state) if state else {})
    m["ActivePointMax"] = ap_max(state.get("exp", 0)) if state else START_MONEY["ActivePointMax"]
    m["ActivePointUpdateTime"] = (state or {}).get("apTime") or now_ms()
    return apidefaults.default("AccountMoney", **m)


def team_deck(d, cls="TeamDeck"):
    strikers = d.get("strikers") or [0, 0, 0]
    if d.get("name", "").startswith("V_CharacterSetting"):   # saved from a missing text tag before the fix
        d["name"] = ""
    return apidefaults.default(cls, DeckNo=d["no"], CharacterIndex1=d["chars"][0], CharacterIndex2=d["chars"][1],
                               CharacterIndex3=d["chars"][2], SupportCharacterIndex1=strikers[0],
                               SupportCharacterIndex2=strikers[1], SupportCharacterIndex3=strikers[2],
                               DeckName=d.get("name", ""), TeamRelationIndex=d.get("relation", 0))


def ok(**fields):
    return {"ResultCode": 0, "ResultMessage": "", **fields}


# ---------------------------------------------------------------- session
@api("session/pcAuth")
def session_pc_auth(req):
    # resultData -> NMRestApi.Session(session_data, country, commonLog)
    player = {
        "playerId": PLAYER_ID, "deviceKey": DEVICE_KEY, "gameCode": "kofg", "gameRegion": "global",
        "joinedCountryCode": "US", "mailUserKey": "",
    }
    session = {
        "accessToken": "offline-" + PLAYER_ID,
        "player": player, **player,  # keys provided at both levels; the ctor reads them via "player"
        "cipherKeyList": [
            {"cipherType": "CIPHER_AES_128_CBC", "secretKey": SESSION_AES_KEY_HEX, "aesInitVec": SESSION_AES_IV_HEX},
            {"cipherType": "CIPHER_RC4_40", "secretKey": SESSION_RC4_KEY_HEX},
        ],
    }
    return ok(resultData=json.dumps(session), country="US", commonLog="")


def table_keys():
    k = json.load(open(os.path.join(HERE, "keys.json"), encoding="utf-8"))
    return k["data_table"], k["localizing"]


@api("session/start")
def session_start(req):
    data, loc = table_keys()
    state = load_state()
    return ok(
        Route=route(state) if state else None,  # no Route = new player -> nickname / character creation
        Unregisted=0,
        ServerUtcTime=now_ms(), ServerZoneOffset=0,
        # NetworkManager.DataTable / LocalizingTable: AES key+IV (hex) used for every table file
        SecurityDataTable={"EncryptionKey": data["key"], "Iv": data["iv"]},
        SecurityLocalizing={"EncryptionKey": loc["key"], "Iv": loc["iv"]},
        AppToken="offline", PcSeq=1, BlockRemainTime=0, AccountType=0, DailyResetHour=5,
        PcBillingData="", Withdraw=None,
    )


@api("session/create")
def session_create(req):
    """New account: nickname + starter character (UIPopup_CreateCharacter.OnClickOK)."""
    with _lock:
        nick = (req.get("NickName") or "Offline")[:16]
        ci = int(req.get("CharacterIndex") or 0)
        state = {"nickname": nick, "created": now_ms(), "exp": 0,
                 "characters": [{"index": ci, "grade": start_grades().get(ci, 3), "exp": 0, "created": now_ms()}],
                 "decks": [{"no": 1, "chars": [ci, 0, 0]}],
                 "money": dict(START_MONEY), "ownAllFighters": True,
                 "tutorials": [] if new_player_flow() == "2023" else list(COMPLETED_TUTORIALS),
                 "unlimited": bool(server_options().get("unlimitedNewAccounts"))}
        save_state(state)
    return ok(
        Route=route(state),
        ProfileCharacter=apidefaults.default("ProfileCharacter", CharacterIndex=ci, TeamDeck=1),
        PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=0),
        AccountMoney=money(state),
        CharacterList=[character(c, start_grades()) for c in owned_characters(state)],
        TeamDeckList=[team_deck(d) for d in state["decks"]],
        BattleCardInvenSize=apidefaults.default("BattleCardInvenSize", Qty=0, MaxSize=200),
    )


# Tutorials an account counts as finished when save.json has no "tutorials" list (accounts made before the 2023
# start existed, or in the 2018 flow): TutorialManager.TryStartMainTutorial starts main tutorial 101 otherwise.
COMPLETED_TUTORIALS = [101]
OPTIONS = os.path.join(HERE, "state", "options.json")


def server_options():
    try:
        return json.load(open(OPTIONS, encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def new_player_flow():
    """"2023" (default): a new player goes nickname -> starter -> main tutorial 101 (story chapter 1, tools/
    gen_story.py); "2018": the battle tutorial first and no main tutorial. tools/new_game.py --flow writes it; the
    client half of the switch is its prefs flag CompleteBattleTutorial (SceneLogin.DisplayNext)."""
    return server_options().get("newPlayerFlow", "2023")


@api("player/profile")
def player_profile(req):
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        # quests already complete at sign-in (e.g. done before they existed) need no "mission complete" notice;
        # the daily ones are announced in the lobby (video 5: "[DAILY] Welcome. Achieved" there)
        if announce_quests(state, (GROWTH_QUEST, ACHIEVEMENT_QUEST)):
            save_state(state)
    shown = next((d["chars"] for d in state.get("decks", []) if d["no"] == REPRESENTATIVE_DECK), None)
    main = shown[0] if shown and shown[0] else state["characters"][0]["index"] if state["characters"] else 0
    boards, cards = core_boards(), battle_cards(state)
    return ok(
        ProfileCharacter=apidefaults.default("ProfileCharacter", CharacterIndex=main,
                                             CharacterIndex2=shown[1] if shown else 0,
                                             CharacterIndex3=shown[2] if shown else 0,
                                             TeamDeck=state.get("deckNo", 1)),
        PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state.get("exp", 0)),
        AccountMoney=money(state),
        CharacterList=[character(c, start_grades()) for c in owned_characters(state)],
        CharacterCoreList=[{"CharacterIndex": c["index"], "CoreTreeIndexList": cores}
                           for c in owned_characters(state) for cores in [unlocked_cores(state, c, boards)] if cores],
        characterAwakenCoreList=ex_core_lists(state),
        TeamDeckList=[team_deck(d) for d in state["decks"]],
        BattleCardList=cards, BattleCardInvenSize=card_inventory(cards),
        ImprintStoneList=imprint_stones(state),
        ImprintStoneInvenSize=apidefaults.default("ImprintStoneInventorySizeWEBData",
                                                  MaxSize=max(200, len(state.get("stones", [])) + 50)),
        BattleCardBookList=[c["BattleCardIndex"] for c in cards],
        ItemList=item_list(state),
        TutorialList=state.get("tutorials", COMPLETED_TUTORIALS), SeriesIndex=1, AccumulateLogin=1,
        # growth, daily and achievement missions: the lobby shows the growth button from this, the Mission screen
        # counts its tiles from it (no achievements known -> the ACHIEVEMENT tile reads as locked)
        QuestList=[e for kind in ANNOUNCED_TYPES for e in quest_list(state, kind)],
        InitialCharacterGroupIndex=1,
    )


# Pages such as the Exchange Shop first ask player/cdnVersion and compare its VersionList with the tables in use
# (DownloadManager.OnCheckTableVersion: "table" and "banner" if present, "lang_global" always - missing threw
# KeyNotFoundException and the page never opened); the same versions as the table download (kofserver.py
# TABLE_PACK_VERSION = tools/make_tablepacks.py), so nothing reads as newer.
TABLE_PACK_VERSION = 1031


@api("player/cdnVersion")
def player_cdn_version(req):
    return ok(VersionList=[{"Key": k, "Value": str(TABLE_PACK_VERSION)} for k in ("table", "lang_global", "prohibited")])


@api("player/tutorialComplete")
def player_tutorial_complete(req):
    with _lock:
        state = load_state()
        done = state.setdefault("tutorials", list(COMPLETED_TUTORIALS))
        for group in req.get("TutorialGroupIndexList") or []:
            if group not in done:
                done.append(group)
        save_state(state)
    return ok(AccountMoney=money(state))


# ---------------------------------------------------------------- story mode (adventure)
# Progress per stage in save.json "stages": {stage index: {"result": best BattleResult, "plays": n}}. Requests are
# appended to logs/story-requests.log.
STORY_LOG = os.path.join(HERE, "logs", "story-requests.log")


def log_story(name, req):
    os.makedirs(os.path.dirname(STORY_LOG), exist_ok=True)
    with open(STORY_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {name} {json.dumps(req, ensure_ascii=False)[:4000]}\n")


SOUL_STAGE = 4                     # StageTable stageType of a soul event (tools/gen_story.py SOUL_OF)
SOUL_RESET_HOUR = 5                # ConfigTable 13006: the soul event entries reset at 5:00 local time
SOUL_ITEM_FIGHTER = {110304: 1023}  # soul stage -> fighter whose souls drop (Athena '94)
SOUL_DROPS = 3                     # souls a win (video 4: three Athena cards)


def soul_day():
    t = time.localtime(time.time() - SOUL_RESET_HOUR * 3600)
    return time.strftime("%Y%m%d", t)


def plays_today(entry):
    return entry.get("today", 0) if entry.get("day") == soul_day() else 0


def stage_entry(state, row):
    done = state.get("stages", {}).get(str(row["stageIndex"]), {}) if state else {}
    missions = done.get("missions", [0, 0, 0])   # the star missions met so far (their indexes; 0 = not yet)
    # a soul stage's PlayCount is today's (the client shows entries left = ConfigTable 13003 - PlayCount)
    plays = plays_today(done) if row.get("stageType") == SOUL_STAGE else done.get("plays", 0)
    return apidefaults.default("AdventureStage", SeriesIndex=row.get("seriesGroup", 0), Chapter=row.get("chapter", 0),
                               StageDifficulty=row.get("difficultyType", 1), StageIndex=row["stageIndex"],
                               BattleResult=done.get("result", 0), PlayCount=plays,
                               Mission1Index=missions[0], Mission2Index=missions[1], Mission3Index=missions[2])


@api("adventure/seriesList")
def adventure_series_list(req):
    log_story("seriesList", req)
    return ok(SeriesList=[apidefaults.default("AdventureSeries", SeriesIndex=r["seriesIndex"], OpenFlag=True,
                                              ProductionFlag=True) for r in table_rows("SeriesTable")])


@api("adventure/stageList")
def adventure_stage_list(req):
    log_story("stageList", req)
    state = load_state()
    series, chapter = req.get("SeriesIndex", 0), req.get("Chapter", 0)
    # The client builds every story stage of StageTable as locked (StoryStageManager.InitStoryStageDataList) and opens
    # the ones listed here, so list what is open: cleared stages, the series' first, and each stage whose
    # predecessor (the stage whose nextStageIndex names it) is cleared. Chapter locks follow their key stage.
    story = [r for r in table_rows("StageTable") if r.get("dungeonType") == 1 and r.get("seriesGroup") == series]
    before = {r["nextStageIndex"]: r["stageIndex"] for r in story if r.get("nextStageIndex")}
    kind = {r["stageIndex"]: r.get("stageType") for r in story}
    for after, prev in list(before.items()):    # a soul stage on the way doesn't gate the stages after it
        while kind.get(prev) == SOUL_STAGE and prev in before:
            prev = before[prev]
        before[after] = prev
    done = (state or {}).get("stages", {})
    cleared = lambda i: done.get(str(i), {}).get("result", 0) > 0
    rows = [r for r in story if (not chapter or r.get("chapter") == chapter)
            and (cleared(r["stageIndex"]) or (r["stageIndex"] not in before and r.get("chapter") != 1199)
                 or cleared(before.get(r["stageIndex"], 0)))]
    claimed = state.get("chapterRewards", {}) if state else {}
    chapters = [apidefaults.default("AdventureChapterMission", SeriesIndex=series, Chapter=c["chapter"],
                                    MissionClearCount=stars(state, c["chapter"]),
                                    RewardTime=claimed.get(str(c["chapter"]), 0))
                for c in table_rows("ChapterTable") if c.get("seriesGroup") == series]
    return ok(StageList=[stage_entry(state, r) for r in rows], ChapterMissionList=chapters,
              StageSeriesMissionList=[series_mission(state, series, NORMAL_DIFFICULTY)])


@api("adventure/selectStageList")
def adventure_select_stage_list(req):
    """StoryStageManager.OpenCheckContentsUnlockTableConditionReady sends the stage indexes of every ContentsUnlockTable
    row of unlockConditionType 5; TakeStageList sets each stage's state to (BattleResult != 0) + 1 and
    IsClearStage needs state 2. Reply one AdventureStage per requested index that has a StageTable row."""
    log_story("selectStageList", req)
    state = load_state()
    rows = {r["stageIndex"]: r for r in table_rows("StageTable")}
    return ok(StageList=[stage_entry(state, rows[i]) for i in (int(x) for x in req.get("StageList") or []) if i in rows])


# Chapter star chests and series progress chests (recon/story/chapter_rewards.md): the client counts stars from the
# stage list's Mission1-3Index and offers the chest; claims are kept in save.json "chapterRewards" {chapter: time}
# and "seriesRewards" {"<series>_<difficulty>": [claimed needMissionCompleteRatio values]}.
NORMAL_DIFFICULTY = 10101


def stars(state, chapter=None, series=None):
    """Star missions met in a chapter (or a whole series) of story stages."""
    got = (state or {}).get("stages", {})
    return sum(sum(1 for m in got.get(str(r["stageIndex"]), {}).get("missions", []) if m)
               for r in table_rows("StageTable") if r.get("dungeonType") == 1
               and (chapter is None or r.get("chapter") == chapter) and (series is None or r.get("seriesGroup") == series))


def series_mission(state, series, difficulty):
    taken = (state or {}).get("seriesRewards", {}).get(f"{series}_{difficulty}", [])
    return apidefaults.default("AdventureSeriesMission", SeriesIndex=series, StageDifficulty=difficulty,
                               ClearMissionCount=stars(state, series=series), RewardList=",".join(map(str, taken)))


@api("adventure/chapterMissionComplete")
def adventure_chapter_mission_complete(req):
    log_story("chapterMissionComplete", req)
    chapter = int(req.get("Chapter") or 0)
    row = next((c for c in table_rows("ChapterTable") if c["chapter"] == chapter), None)
    with _lock:
        state = load_state()
        claimed = state.setdefault("chapterRewards", {})
        item_ids, fighters = [], []
        if row and str(chapter) not in claimed and stars(state, chapter) >= row.get("chapterStageMaxValue", 0):
            claimed[str(chapter)] = now_ms()
            _, item_ids, fighters = give_rewards(state, row.get("chaperCompleteRewardGroup", 0))
        save_state(state)
    return ok(AccountMoney=money(state), RewardItemList=item_list(state, item_ids), RewardCharacterList=fighters)


@api("adventure/seriesMissionComplete")
def adventure_series_mission_complete(req):
    log_story("seriesMissionComplete", req)
    series, difficulty = int(req.get("SeriesIndex") or 0), int(req.get("StageDifficulty") or NORMAL_DIFFICULTY)
    index = int(req.get("SeriesMissionCompleteIndex") or 0)
    group = next((s.get("normalSeriesMissionCompleteGroup", 0) for s in table_rows("SeriesTable")
                  if s["seriesIndex"] == series), 0)
    chests = [r for r in table_rows("SeriesMissionCompleteTable") if r.get("seriesMissionCompleteGroup") == group]
    row = next((r for r in chests if r["seriesMissionCompleteIndex"] == index), None)
    if row is None and 0 <= index < len(chests):      # the client may send the chest's position instead
        row = chests[index]
    with _lock:
        state = load_state()
        taken = state.setdefault("seriesRewards", {}).setdefault(f"{series}_{difficulty}", [])
        total = 3 * sum(1 for r in table_rows("StageTable") if r.get("dungeonType") == 1
                        and r.get("seriesGroup") == series and r.get("stageType") == 2)
        item_ids, fighters = [], []
        if row and row["needMissionCompleteRatio"] not in taken and total and \
                stars(state, series=series) * 100 // total >= row["needMissionCompleteRatio"]:
            taken.append(row["needMissionCompleteRatio"])
            _, item_ids, fighters = give_rewards(state, row.get("seriesMissionCompleteRewardGroup", 0))
        save_state(state)
    return ok(StageSeriesMission=series_mission(state, series, difficulty), AccountMoney=money(state),
              RewardItemList=item_list(state, item_ids), RewardCharacterList=fighters)


@api("adventure/stageStart")
def adventure_stage_start(req):
    log_story("stageStart", req)
    with _lock:
        state = load_state()
        spend_ap(state, int(req.get("UsedActivePoint") or 0))
        save_state(state)
    index = int(req.get("StageIndex") or 0)
    with _lock:
        state = load_state()
        state["runSupporter"] = int(req.get("StrikerType") or 0) if int(req.get("StrikerUsn") or 0) else 0
        state["runAuto"] = int(req.get("AutoBattleCount") or 0) > 0     # AUTO BATTLE repeats pay no supporter points
        save_state(state)
    # a soul event's boss drops the fighter's souls (shown as dropped cards on the result)
    drops = [reward(ITEM_GOODS, 1, SOUL_ITEM_BASE + SOUL_ITEM_FIGHTER[index])] * SOUL_DROPS \
        if index in SOUL_ITEM_FIGHTER else []
    # the battle supporter is built from the reply's Striker fields (Parse_AdventureStageStart): echo the request's
    # the win's gold drops in battle (StageDropTable row with gold way Random, tools/gen_story.py): each total is
    # spread over that kind of monster (DropItemManager.MakeGoldData); the result pays the whole STAGE_GOLD anyway
    gold = STAGE_GOLD.get(index, CLEAR_GOLD)
    jaco, elite = gold * 2 // 5, gold // 5
    return ok(AccountMoney=money(state), StagePlayToken=now_ms(), DropBossList=drops,
              DropGoldJaco=jaco, DropGoldElite=elite, DropGoldBoss=gold - jaco - elite,
              **{k: req.get(k) for k in ("StrikerType", "StrikerUsn", "StrikerIndex", "StrikerGameDb", "StrikerNickName")
                 if req.get(k) not in (None, "")})


@api("adventure/stageStory")
def adventure_stage_story(req):
    """A story-only episode (StageTable stageType 3, e.g. chapter 2 EP.1): the client plays its startDialog over the
    stage list, then sends this; the first time it pays the first-clear rubies (video 3: 5, "Mission Clear Reward
    acquired!") and the stage reads cleared (the next episode opens)."""
    log_story("stageStory", req)
    index = int(req.get("StageIndex") or 0)
    with _lock:
        state = load_state()
        entry = state.setdefault("stages", {}).setdefault(str(index), {"result": 0, "plays": 0})
        first = entry["result"] == 0
        entry["plays"] += 1
        entry["result"] = max(entry["result"], WIN)
        if first:
            wallet = state.setdefault("money", dict(START_MONEY))
            wallet["Cash"] = wallet.get("Cash", 0) + FIRST_CLEAR_RUBIES
        completed = announce_quests(state)
        save_state(state)
    return ok(StageIndex=index, FirstClearFlag=1 if first else 0, AccountMoney=money(state),
              FirstClearRewardList=[reward(RUBY_GOODS, FIRST_CLEAR_RUBIES)] if first else [],
              CompleteQuestList=completed)


# ---------------------------------------------------------------- AP, team decks
@api("player/activePointGive")
def player_active_point_give(req):
    """The top bar's AP timer ran out: hand over the regained AP (regen_ap)."""
    with _lock:
        state = load_state()
        wallet = regen_ap(state)
        save_state(state)
    return ok(ActivePoint=wallet["ActivePoint"], ActivePointUpdateTime=state["apTime"], ServerTime=now_ms())


@api("character/teamDeckUpdate")
def character_team_deck_update(req):
    """Team formation (QUEST INFO, Team menu): save each deck's three fighters and strikers."""
    with _lock:
        state = load_state()
        decks = {d["no"]: d for d in state.setdefault("decks", [])}
        for vo in req.get("TeamDeckList") or []:
            if vo.get("DeckNo") is not None:    # deck 0 is real: the client names it "TEAM 0" (dungeon teams)
                no = int(vo.get("DeckNo") or 0)
                decks[no] = {"no": no, "chars": [int(vo.get(f"CharacterIndex{i}") or 0) for i in (1, 2, 3)],
                             "strikers": [int(vo.get(f"SupportCharacterIndex{i}") or 0) for i in (1, 2, 3)],
                             # a name the client built from a missing text tag is not a name
                             "name": "" if (vo.get("DeckName") or "").startswith("V_CharacterSetting")
                             else vo.get("DeckName") or "",
                             "relation": int(vo.get("TeamRelationIndex") or 0)}   # the chosen team relation
        state["decks"] = [decks[k] for k in sorted(decks)]
        completed = announce_quests(state)
        save_state(state)
    return ok(TeamDeckList=[team_deck(d, "TeamDeckVO") for d in state["decks"]], CompleteQuestList=completed)


@api("character/useTeamDeck")
def character_use_team_deck(req):
    with _lock:
        state = load_state()
        state["deckNo"] = int(req.get("DeckNo") or 1)
        save_state(state)
    return ok()


# The lobby's fighters are the Representative Team Deck (TeamDeckType 55: TeamDeckManager.SetSelectedTeamDeck gives the
# lobby scene deck 55, UIView_Lobby.Initialize shows its fighters and its arrows step through them, the slot kept in
# PlayerPrefs LobbyCharacterIndex). Changing them sends player/profileCharacterSet (RepresentativeTeamDeckSetRequest:
# characterIndex, characterIndex2, characterIndex3, leaderPower, teamDeck 55) and the client makes the deck from the
# reply's fields (Controller_CharacterSelect_UX.RecvRepresentativeTeamDeckUpdate), so the reply echoes them. The deck
# is kept with the others (save.json "decks"), so the TeamDeckList of player/profile brings it back.
REPRESENTATIVE_DECK = 55


@api("player/profileCharacterSet")
def player_profile_character_set(req):
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        no = int(req.get("teamDeck") or REPRESENTATIVE_DECK)
        chars = [int(req.get(k) or 0) for k in ("characterIndex", "characterIndex2", "characterIndex3")]
        decks = {d["no"]: d for d in state.setdefault("decks", [])}
        decks[no] = {**decks.get(no, {}), "no": no, "chars": chars}
        state["decks"] = [decks[k] for k in sorted(decks)]
        state["leaderPower"] = int(req.get("leaderPower") or 0)
        save_state(state)
    return ok(characterIndex=chars[0], characterIndex2=chars[1], characterIndex3=chars[2],
              leaderPower=state["leaderPower"], teamDeck=no)


# Player storage: the client keeps small JSON blobs on the server by category (TeamDeckManager.StorageDecks in 5:
# the Guild Raid's team per difficulty, "GuildDungeon40101": "1200,1268,1043"); save.json "storage" {category: ...}
@api("player/storageSet")
def player_storage_set(req):
    with _lock:
        state = load_state()
        state.setdefault("storage", {})[str(int(req.get("Category") or 0))] = {
            "Version": int(req.get("Version") or 0), "Datas": req.get("Datas") or "", "UpdateTime": now_ms()}
        save_state(state)
    return ok()


@api("player/storageGet")
def player_storage_get(req):
    category = int(req.get("Category") or 0)
    kept = (load_state() or {}).get("storage", {}).get(str(category), {})
    return ok(Category=category, Version=kept.get("Version", 0), Datas=kept.get("Datas", ""),
              UpdateTime=kept.get("UpdateTime", 0))


# EXP for a won story stage, as in the 2023 videos: +24 rank EXP a stage; fighter EXP +300 for "First Step" (a Lv 1
# starter to Lv 2; 300 ends Lv 1 for every levelingType, gen_growth.leveling_rows), +150 for chapter 1's other two
# stages and "Pointless Pursuit", +160 from "Wrong Deductions" on (video 3; ours for later stages). The client sends
# the EXP it had (it adds nothing itself) and shows what comes back.
STORY_ACCOUNT_EXP = 24
STORY_ACCOUNT_EXP_OF = {110304: 22}   # the soul event gave +22 (video 4)
STORY_FIGHTER_EXP = {110101: 300, 110102: 150, 110103: 150, 110202: 150, 110303: 170, 110304: 170}   # video 4
STORY_FIGHTER_EXP_DEFAULT = 160
WIN = 1  # BattleResult
# Rewards, as the 2023 video shows them for chapter 1 (gen_story.REWARD_GROUPS shows the same in the client): 3 rubies
# a star mission (once each), 5 for the first clear, 5 once all three missions are met, 100 gold a win; a rank up
# refills AP and gives 10 rubies (the video's AP potion is not given: no such item offline yet).
GOLD_GOODS, RUBY_GOODS, ITEM_GOODS = 1, 2, 13   # GoodsType
MISSION_RUBIES, FIRST_CLEAR_RUBIES, ALL_CLEAR_RUBIES, CLEAR_GOLD, RANK_UP_RUBIES = 3, 5, 5, 100, 10
STAGE_GOLD = {110303: 110, 110304: 110}     # gold of a win where it isn't CLEAR_GOLD (video 4 gold trace)
# A rank up also gives an AP potion (+30 AP; tools/gen_growth.AP_POTIONS), as in the 2023 video, and a win gives the
# team leader +2 affinity and the other fighters +1 (video 3: Kyo "AFFINITY +2", Baseball Yuri "+1").
RANK_UP_ITEMS = {1201: 1}
AFFINITY_LEADER, AFFINITY_OTHERS = 2, 1


def account_level(exp):
    """The client's rule (AccountLevelingTable.GetAccountLevel): the first rank whose expAccumulate is above exp."""
    for r in sorted(table_rows("AccountLevelingTable"), key=lambda r: r["accountLevel"]):
        if exp < r.get("expAccumulate", 0):
            return r["accountLevel"]
    return 1


def reward(goods, count, index=0):
    """A RewardContents entry. The client takes GoodsType, ContentsIndex, ContentsGrade and ContentsCount
    (NetworkManagerWEB.TakeRewardContents -> DBData.Goods); Count alone showed an icon with no amount."""
    return apidefaults.default("RewardContents", GoodsType=goods, Count=count, ContentsIndex=index,
                               ContentsCount=count)


def mission_reward_lists(missions, got, rewards_of):
    """Mission1-3RewardList for the YOU WIN rows. UIPage_StoryMission.SetStarMission sorts its rows with the missions
    met now or before first (StarMissionManager.GetSortedMission: GetState GET / CLEAR, then the rest, each in stage
    order) and gives row n the n-th list; a row without one showed neither success nor failure (no text, a stray
    reward icon). So every mission of the stage (its StageMissionTable index, 0 = none) gets its reward listed, in
    that order: display only, what is paid goes through AccountMoney and the inventory."""
    slots = [i for i, m in enumerate(missions) if m]
    order = [i for i in slots if got[i]] + [i for i in slots if not got[i]]
    return {f"Mission{n + 1}RewardList": rewards_of(missions[i]) for n, i in enumerate(order)}


@api("adventure/stageEnd")
def adventure_stage_end(req):
    log_story("stageEnd", req)
    with _lock:
        state = load_state()
        index, result = int(req.get("StageIndex", 0)), int(req.get("BattleResult", 0))
        entry = state.setdefault("stages", {}).setdefault(str(index), {"result": 0, "plays": 0})
        first = entry["result"] == 0 and result > 0
        entry["plays"] += 1
        entry["result"] = max(entry["result"], result)
        count_play(state, "soul" if index in SOUL_ITEM_FIGHTER else "story")
        supporter = state.pop("runSupporter", 0)
        if state.pop("runAuto", False):                           # the guides: none for auto-battle farming
            supporter = 0
        if result == WIN and supporter in SUPPORT_POINTS_CONFIG:   # video 4: a mail with the supporter's points
            points = next((int(r.get("value1") or 0) for r in table_rows("ConfigTable")
                           if r["configIndex"] == SUPPORT_POINTS_CONFIG[supporter]), 0)
            if points:
                send_post(state, POST_SUPPORT, FRIEND_POINT_GOODS, points)
        won = result == WIN
        account = req.get("PlayerAccount") or {}
        before = max(state.get("exp", 0), int(account.get("Exp") or 0))
        state["exp"] = before + (STORY_ACCOUNT_EXP_OF.get(index, STORY_ACCOUNT_EXP) if won else 0)
        if index in SOUL_ITEM_FIGHTER:      # entries used today, and the souls the boss dropped
            if entry.get("day") != soul_day():
                entry["day"], entry["today"] = soul_day(), 0
            entry["today"] = entry.get("today", 0) + 1
            if won:
                inv = items(state)
                soul = str(SOUL_ITEM_BASE + SOUL_ITEM_FIGHTER[index])
                inv[soul] = int(inv.get(soul, 0)) + SOUL_DROPS
        fighter_exp = STORY_FIGHTER_EXP.get(index, STORY_FIGHTER_EXP_DEFAULT) if won else 0
        for n, c in enumerate(c for c in req.get("CharacterList") or [] if c.get("CharacterIndex")):
            fighter = character_state(state, int(c["CharacterIndex"]))   # the fighters that played, leader first
            fighter["exp"] = max(fighter.get("exp", 0), int(c.get("Exp", 0))) + fighter_exp
            fighter["affection"] = (max(fighter.get("affection", 0), int(c.get("AffectionExp") or 0))
                                    + ((AFFINITY_LEADER if n == 0 else AFFINITY_OTHERS) if won else 0))
        # star missions the client says were met (their StageMissionTable indexes), paid the first time each
        met = [int(req.get(f"Mission{i}Index") or 0) if won else 0 for i in (1, 2, 3)]
        got = entry.setdefault("missions", [0, 0, 0])
        new = [m if m and not got[i] else 0 for i, m in enumerate(met)]
        got[:] = [g or n for g, n in zip(got, new)]
        all_clear = won and all(got) and not entry.get("allClear")
        entry["allClear"] = entry.get("allClear") or all_clear
        rank_up = won and account_level(state["exp"]) > account_level(before)
        rubies = (MISSION_RUBIES * sum(1 for m in new if m) + (FIRST_CLEAR_RUBIES if first else 0)
                  + (ALL_CLEAR_RUBIES if all_clear else 0) + (RANK_UP_RUBIES if rank_up else 0))
        wallet = state.setdefault("money", dict(START_MONEY))
        wallet["Cash"] = wallet.get("Cash", 0) + rubies
        wallet["Gold"] = wallet.get("Gold", 0) + (STAGE_GOLD.get(index, CLEAR_GOLD) if won else 0)
        if rank_up:
            wallet["ActivePoint"] = max(wallet.get("ActivePoint", 0), ap_max(state["exp"]))
            inv = items(state)
            for k, n in RANK_UP_ITEMS.items():
                inv[str(k)] = int(inv.get(str(k), 0)) + n
        completed = announce_quests(state)
        save_state(state)
    stage = next((r for r in table_rows("StageTable") if r["stageIndex"] == index), {})
    missions = mission_reward_lists([stage.get(f"mission{i}Index", 0) for i in (1, 2, 3)], got,
                                    lambda m: [reward(RUBY_GOODS, MISSION_RUBIES)])
    return ok(StageIndex=index, BattleResult=result, FirstClearFlag=1 if first else 0, AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state.get("exp", 0)),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple",
                                    start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              FirstClearRewardList=[reward(RUBY_GOODS, FIRST_CLEAR_RUBIES)] if first else [],
              MissionAllRewardList=[reward(RUBY_GOODS, ALL_CLEAR_RUBIES)] if all_clear else [],
              ClearRewardList=[reward(GOLD_GOODS, STAGE_GOLD.get(index, CLEAR_GOLD))] if won else [],
              AccountLevelUpFlag=1 if rank_up else 0,
              AccountLevelUpRewardList=([reward(ITEM_GOODS, n, k) for k, n in RANK_UP_ITEMS.items()]
                                        + [reward(RUBY_GOODS, RANK_UP_RUBIES)]) if rank_up else [],
              CompleteQuestList=completed, **missions)


# ---------------------------------------------------------------- Power Up Dungeon (recon/story/exp_dungeon.md)
# The EXP dungeon (tools/gen_dungeon.py) is open while player/poll's DownloadScheduleList holds its schedule: an
# OperateSchedule {Category 2 Dungeon, SubCategory 2 Growth, Index = QuestEventScheduleTable row} with OffOnSched 1
# (always open). Each poll reply replaces the client's whole schedule list, so every one carries it.
DUNGEON_CATEGORY, GROWTH_DUNGEON, ALWAYS_OPEN = 2, 2, 1
# the EXP dungeon, the Gold Dungeon, the Evolution Dungeon's five element tabs, the (locked) Core Dungeon
DUNGEON_SCHEDULES = [3201, 3101, 3301, 3302, 3303, 3304, 3305, 3501,
                     106]   # Tower of Trials: QuestEventGroup.IsToday -> ScheduleTableData -> DungeonController.IsOpenDungeon(2, 106);
                            # without it BATTLE stopped at "SpecialQuest Notice UseContent" (UIView_StoryStageInfo.PlayEventQuest)
# Transcendence Dungeon (real mobile tables, tools/import_dungeons.py): Hall of Elements 41001-41005
# (questEventType 10) + Advent 42001-42006 (type 2). EDungeonType: type 3 keeps its Growth banner
# (SubCategory 2); Advent and Hall of Elements are Event banners (SubCategory 3, Advent SubGroup [1]).
TRANSCEND_QES = (41001, 41002, 41003, 41004, 41005, 42001, 42002, 42003, 42004, 42005, 42006)
EVENT_DUNGEON = 3
# Hall of Elements (real mobile rules, the community build's v158): one group for the five elements
# (QuestEventGroup 41000) whose QuestEventGroupList entry carries today's entry count -- the client's
# EventQuestShortcut.OnCheckSpecialOpen reads it before it ever opens the stage list (without it the
# entry hangs on NOW LOADING). 3 entries a day across the elements, stages unlock in sequence per
# element, and clear rewards pay "memory marker" items 3999991-95 that the game swaps for a random
# fighter Memory of that element (item 3000000 + characterIndex; items imported from the mobile set).
HOE_QES = (41001, 41002, 41003, 41004, 41005)
HOE_GROUP, HOE_DAILY, HOE_MARKER = 41000, 3, 3_999_990
HOE_ELEMENTS = {HOE_MARKER + 1: 1, HOE_MARKER + 2: 2, HOE_MARKER + 3: 3, HOE_MARKER + 4: 4, HOE_MARKER + 5: 5}


def hoe_prog(state):
    p = state.setdefault("hoe", {})
    today = time.strftime("%Y-%m-%d")
    if p.get("day") != today:
        p["day"] = today
        p["n"] = 0
    return p


def hoe_group(state):
    # ReOpenEndTime feeds QuestEventGroup's ReOpenEndTime (IsToday): a past date keeps the group open
    return {"QuestEventGroup": HOE_GROUP, "ClearCount": int(hoe_prog(state).get("n") or 0),
            "ReOpenEndTime": "2000-01-01T00:00:00"}


def hoe_open(state):
    """The Hall of Elements stages the list may show: each element's cleared ones plus the next."""
    open_ids, played = set(), state.get("questEventStages", {})
    for qe in HOE_QES:
        rows = sorted((r for r in table_rows("QuestEventStageTable")
                       if int(r.get("questEventIndex") or 0) == qe),
                      key=lambda r: int(r.get("questEventStageLevel") or 0))
        for r in rows:
            sid = int(r["questEventStageIndex"])
            open_ids.add(sid)
            if not played.get(str(sid), {}).get("result"):
                break
    return open_ids


def hoe_memory(element):
    """A random fighter Memory of the element (markers 3999991-95 stand for one in the reward groups)."""
    import random
    have = {r.get("itemIndex") for r in table_rows("ItemTable")}
    pool = [3_000_000 + int(c["characterIndex"]) for c in player_character_rows()
            if int(c.get("synastryType") or 0) == element and 3_000_000 + int(c["characterIndex"]) in have]
    return random.choice(pool) if pool else 0
# The Gold Dungeon (questEventSubType 31, tools/gen_dungeon.py): its pot is the StageDropTable row's stageDropGoldMax,
# where the client ends the run ("a fixed amount of gold", the fan guide). questEventStart hands out gold pools; the
# client splits each over the actors it counts in the stage script (DropItemManager.MakeGoldData: Jaco = the script's
# normal dolls, 8 on EASY, Elite = its gold doll, Gimmick1 = the six Lucky Cats, Gimmick2/3 none) and adds the gold as
# it drops. questEventEnd pays the DropGold the run gained (up to the pot); AUTO-CLEAR pays the pot, a full run.
# Pool shares of the pot (ours): dolls 75 %, gold doll 15 %, cats 60 % (10 % each), so a strong team reaches the pot
# (with the 30/30/40 % split a full EASY run stopped at 70 %: the gold doll is easy to miss).
GOLD_DUNGEON = 31
GOLD_SHARES = {"DropGoldJaco": 75, "DropGoldElite": 15, "DropGoldGimmick1": 60}
# Video 5's EASY run: +20 rank EXP for AP 10 (2 a point; the other difficulties ours by the same rule), no fighter
# EXP, affinity +2 leader / +1 the others as in story. A lost run left the AP where it was: the client ignores a lost
# run's AccountMoney (Parse_QuestEventEnd returns early unless BattleResult is 1), so the AP is charged only when a
# run is won (questEventEnd), not at the start.
QUEST_EVENT_EXP_PER_AP = 2


def apply_rank_up(state, before):
    """A rank up from the rank EXP gained since `before` (as adventure/stageEnd): AP refilled, rubies and the AP
    potion. -> (AccountLevelUpFlag, AccountLevelUpRewardList)"""
    if account_level(state["exp"]) <= account_level(before):
        return 0, []
    wallet = regen_ap(state)
    wallet["Cash"] = wallet.get("Cash", 0) + RANK_UP_RUBIES
    wallet["ActivePoint"] = max(wallet.get("ActivePoint", 0), ap_max(state["exp"]))
    inv = items(state)
    for k, n in RANK_UP_ITEMS.items():
        inv[str(k)] = int(inv.get(str(k), 0)) + n
    return 1, [reward(ITEM_GOODS, n, k) for k, n in RANK_UP_ITEMS.items()] + [reward(RUBY_GOODS, RANK_UP_RUBIES)]


def dungeon_schedules():
    types = {r["questEventIndex"]: int(r.get("questEventType") or 0) for r in table_rows("QuestEventTable")}
    out = [apidefaults.default("OperateSchedule", Version=1, Category=DUNGEON_CATEGORY, SubCategory=GROWTH_DUNGEON,
                               Index=i, Detail=apidefaults.default("OperateScheduleData", SubGroup=[i],
                                                                   OffOnSched=ALWAYS_OPEN))
           for i in DUNGEON_SCHEDULES]
    # The transcendence events read one schedule two ways: the hub's banner list filters Category 2 /
    # SubCategory 3 (EDungeonType Growth/Event), while EventQuestShortcut.IsOpenDungeon admits the
    # card only when a Category 3 schedule carries the event's index -- so each event sends both.
    out += [apidefaults.default("OperateSchedule", Version=1, Category=c, SubCategory=EVENT_DUNGEON, Index=i,
                                TagList=[1] if types.get(i) == 2 else [],
                                Detail=apidefaults.default("OperateScheduleData",
                                                           SubGroup=[1] if types.get(i) == 2 else [],
                                                           OffOnSched=ALWAYS_OPEN))
            for i in TRANSCEND_QES for c in (DUNGEON_CATEGORY, EVENT_DUNGEON)]
    return out


@api("session/poll")         # before sign-in (PollCateg "new user"); player/poll "first" follows at sign-in
@api("player/poll")
def player_poll(req):
    import ext_dispatch                            # the lobby DISPATCH button needs its schedule (category 30)
    return ok(DownloadScheduleList=dungeon_schedules() + roulette_schedules() + raid_schedules() + tr_schedules()
              + ext_dispatch.schedules(),
              PollHash=req.get("PollHash") or "",
              ClientTick=int(req.get("ClientTick") or 0))


LIMIT_DAILY = 2   # QuestEventStageTable.limitPlayType (LimitPlayType DAILY; limitPlayValue1 = runs a day)


def quest_event_stage_row(index):
    return next((r for r in table_rows("QuestEventStageTable") if r["questEventStageIndex"] == index), {})


def quest_event_stage(state, row):
    """QuestEventStageWEBData of a played stage: BattleResult > 0 = cleared (the next difficulty opens)."""
    done = (state or {}).get("questEventStages", {}).get(str(row["questEventStageIndex"]), {})
    missions = done.get("missions", [0, 0, 0])
    clears = done.get("clears", 0)
    if row.get("limitPlayType") == LIMIT_DAILY and state:   # a daily-limited stage counts today's clears
        clears = daily(state).get("questEventClears", {}).get(str(row["questEventStageIndex"]), 0)
    return apidefaults.default("QuestEventStageWEBData", QuestEventIndex=row.get("questEventIndex", 0),
                               QuestEventStageIndex=row["questEventStageIndex"],
                               StageDifficulty=row.get("difficultyType", 0), BattleResult=done.get("result", 0),
                               ClearCount=clears, Mission1Index=missions[0],
                               Mission2Index=missions[1], Mission3Index=missions[2])


@api("questEvent/questEventList")
def quest_event_list(req):
    """Stage states of the quest events: the stages the account has played (no entry = never played -> NEW!).
    The Transcendence stages are always sent: a stage the server never lists reads as locked; the Hall of
    Elements list is its cleared stages plus the next of each element, and the group entry carries today's
    entry count (the client's banner shortcut reads it before opening the stage list)."""
    log_story("questEventList", req)
    state = load_state() or {}
    played = state.get("questEventStages", {})
    hoe_ids = hoe_open(state)
    stages = [quest_event_stage(state, r) for r in table_rows("QuestEventStageTable")
              if str(r["questEventStageIndex"]) in played
              or int(r.get("questEventIndex") or 0) in TRANSCEND_QES]
    stages = [s for s in stages if int(s.get("QuestEventIndex") or 0) not in HOE_QES
              or int(s.get("QuestEventStageIndex") or 0) in hoe_ids]
    return ok(QuestEventList=[apidefaults.default("QuestEventWEBData", QuestEventIndex=r["questEventIndex"])
                              for r in table_rows("QuestEventTable")],
              QuestEventStageList=stages,
              QuestEventGroupList=[hoe_group(state)],
              QuestEventTicketRechargeList=[], HotTimeEnterList=[], MarathonPlayCheckList=[])


@api("questEvent/questEventOpen")
def quest_event_open(req):
    """One event's stage states, asked entering a dungeon from its banner."""
    qe = int(req.get("QuestEventIndex") or 0)
    state = load_state() or {}
    rows = [r for r in table_rows("QuestEventStageTable") if int(r.get("questEventIndex") or 0) == qe]
    if qe in HOE_QES:
        ids = hoe_open(state)
        rows = [r for r in rows if int(r["questEventStageIndex"]) in ids]
    return ok(QuestEvent=apidefaults.default("QuestEventWEBData", QuestEventIndex=qe),
              QuestEventStageList=[quest_event_stage(state, r) for r in rows],
              QuestEventGroupList=[hoe_group(state)] if qe in HOE_QES else [])


@api("questEvent/questEventStart")
def quest_event_start(req):
    log_story("questEventStart", req)
    index, ap = int(req.get("QuestEventStageIndex") or 0), int(req.get("UsedActivePoint") or 0)
    row = quest_event_stage_row(index)
    token = now_ms()
    # coins in battle: the clear reward's gold spread over the disciples and the boss (the result pays it once);
    # the Gold Dungeon's pot instead, over its dolls and the Lucky Cat (paid as picked up, quest_event_end)
    gold = sum(r.get("contentsCountMin", 0) for r in table_rows("RewardGroupTable")
               if r.get("rewardGroup") == row.get("questEventStageClearRewardGroup") and r.get("rewardType") == GOLD_GOODS)
    pot = gold_pot(row)
    with _lock:
        state = load_state()
        state["runQuestEvent"] = {"stage": index, "ap": ap, "token": token, "pot": pot}
        state["runSupporter"] = int(req.get("StrikerType") or 0) if int(req.get("StrikerUsn") or 0) else 0
        state["runAuto"] = int(req.get("AutoBattleCount") or 0) > 0     # AUTO BATTLE repeats pay no supporter points
        save_state(state)
    drops = ({k: pot * share // 100 for k, share in GOLD_SHARES.items()}
             if pot else {"DropGoldJaco": gold * 2 // 3, "DropGoldBoss": gold - gold * 2 // 3})
    return ok(AccountMoney=money(state), QuestEventPlayToken=token, **drops,
              **{k: req.get(k) for k in ("StrikerType", "StrikerUsn", "StrikerIndex", "StrikerGameDb", "StrikerNickName")
                 if req.get(k) not in (None, "")})


def quest_event_subtype(stage_row):
    return next((r.get("questEventSubType", 0) for r in table_rows("QuestEventTable")
                 if r["questEventIndex"] == stage_row.get("questEventIndex")), 0)


def gold_pot(stage_row):
    """A Gold Dungeon stage's pot (its StageDropTable stageDropGoldMax); 0 for other stages."""
    if quest_event_subtype(stage_row) != GOLD_DUNGEON:
        return 0
    return next((r.get("stageDropGoldMax", 0) for r in table_rows("StageDropTable")
                 if r["stageDropIndex"] == stage_row.get("stageDropIndex")), 0)


@api("questEvent/questEventEnd")
def quest_event_end(req):
    log_story("questEventEnd", req)
    index, result = int(req.get("QuestEventStageIndex") or 0), int(req.get("BattleResult") or 0)
    row, won = quest_event_stage_row(index), result == WIN
    with _lock:
        state = load_state()
        run = state.pop("runQuestEvent", {})
        entry = state.setdefault("questEventStages", {}).setdefault(str(index), {"result": 0, "plays": 0, "clears": 0})
        first = entry["result"] == 0 and won
        entry["plays"] += 1
        entry["clears"] += 1 if won else 0
        if won:   # today's clears, for stages with a daily limit (QuestEventStageTable limitPlayType 2)
            today = daily(state).setdefault("questEventClears", {})
            today[str(index)] = today.get(str(index), 0) + 1
        entry["result"] = max(entry["result"], result)
        count_play(state, "exp")
        if won and run.get("stage") == index:
            spend_ap(state, run.get("ap", 0))
        if run.get("stage") == index and run.get("pot"):       # the Gold Dungeon: the gold the run picked up
            wallet = state.setdefault("money", dict(START_MONEY))
            wallet["Gold"] = wallet.get("Gold", 0) + min(int(req.get("DropGold") or 0), run["pot"])
        supporter = state.pop("runSupporter", 0)
        if state.pop("runAuto", False):
            supporter = 0
        if won and supporter in SUPPORT_POINTS_CONFIG:
            points = next((int(r.get("value1") or 0) for r in table_rows("ConfigTable")
                           if r["configIndex"] == SUPPORT_POINTS_CONFIG[supporter]), 0)
            if points:
                send_post(state, POST_SUPPORT, FRIEND_POINT_GOODS, points)
        account = req.get("PlayerAccount") or {}
        before = max(state.get("exp", 0), int(account.get("Exp") or 0))
        state["exp"] = before + (QUEST_EVENT_EXP_PER_AP * row.get("activePointValue", 0) if won else 0)
        for n, c in enumerate(c for c in req.get("CharacterList") or [] if c.get("CharacterIndex")):
            fighter = character_state(state, int(c["CharacterIndex"]))
            fighter["exp"] = max(fighter.get("exp", 0), int(c.get("Exp", 0)))
            fighter["affection"] = (max(fighter.get("affection", 0), int(c.get("AffectionExp") or 0))
                                    + ((AFFINITY_LEADER if n == 0 else AFFINITY_OTHERS) if won else 0))
        # star missions (paid once each, their StageMissionTable reward group), first clear, the clear rewards
        met = [int(req.get(f"Mission{i}Index") or 0) if won else 0 for i in (1, 2, 3)]
        got = entry.setdefault("missions", [0, 0, 0])
        new = [m if m and not got[i] else 0 for i, m in enumerate(met)]
        got[:] = [g or n for g, n in zip(got, new)]
        mission_groups = {r["stageMissionIndex"]: r.get("missionCompleteRewardGroup", 0)
                          for r in table_rows("StageMissionTable")}
        for m in new:
            if m:
                give_rewards(state, mission_groups.get(m, 0))
        missions = mission_reward_lists([row.get(f"mission{i}Index", 0) for i in (1, 2, 3)], got,
                                        lambda m: reward_contents(mission_groups.get(m, 0)))
        is_hoe = int(row.get("questEventIndex") or 0) in HOE_QES
        first_clear = give_rewards(state, row.get("questEventStageFirstClearRewardGroup", 0))[0] if first else []
        clear = give_rewards(state, row.get("questEventStageClearRewardGroup", 0))[0] if won else []
        # Parse_QuestEventEnd adds each RewardItemList entry's Qty to the inventory (ItemInventory.InnerAddCount):
        # the gained amounts, not the totals
        gained = [{"ItemIndex": c["ContentsIndex"], "Qty": c["ContentsCount"], "Lock": 0, "UpdateTime": now_ms()}
                  for c in clear if c["GoodsType"] == ITEM_GOODS]
        rank_up, rank_rewards = apply_rank_up(state, before)
        completed = announce_quests(state)
        save_state(state)
    return ok(QuestEventStageIndex=index, BattleResult=result, FirstClearFlag=1 if first else 0,
              AccountMoney=money(state), PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple", start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              RewardItemList=gained, ClearRewardList=clear, FirstClearRewardList=first_clear,
              AccountLevelUpFlag=rank_up, AccountLevelUpRewardList=rank_rewards,
              # null, not the defaulted objects: Parse_QuestEventEnd turns any RewardComedown (a descent's reward box)
              # into a result reward, and item 0 x0 made UIUnit_ResultReward.SetData throw (RESULT stuck on "No
              # rewards."); RemainItem would set inventory item 0
              RewardComedown=None, RemainItem=None,
              QuestEvent=apidefaults.default("QuestEventWEBData", QuestEventIndex=row.get("questEventIndex", 0)),
              QuestEventStage=quest_event_stage(state, row) if row else apidefaults.default("QuestEventStageWEBData"),
              CompleteQuestList=completed,
              **({"QuestEventGroup": hoe_group(state)} if is_hoe else {}), **missions)


# ---------------------------------------------------------------- AUTO-CLEAR (mop-up)
# QUEST INFO's AUTO-CLEAR repeats a stage whose star missions are all met without playing it (tools/gen_story.py
# MOPUP_COST): a run costs an AUTO-CLEAR TICKET and the stage's AP and pays what a won run pays, without missions or
# first clear. The client groups RewardContentsList by run (NetworkManagerWEB.TakeRewardContentsList: an entry's Count
# is the run number, ContentsCount the amount), adds RewardItemList to the inventory and sets the tickets left from
# MopupTicketItem.
AUTO_CLEAR_TICKET = 1302          # tools/gen_growth.AUTO_CLEAR_TICKETS


def mopup_runs(state, req):
    """Runs asked for, capped by the tickets owned; takes the tickets. -> (runs, MopupTicketItem)"""
    inv = items(state)
    have = int(inv.get(str(AUTO_CLEAR_TICKET), 0))
    runs = max(0, min(int(req.get("StageMopUpCount") or 0), have))
    inv[str(AUTO_CLEAR_TICKET)] = have - runs
    return runs, {"ItemIndex": AUTO_CLEAR_TICKET, "Qty": have - runs, "Lock": 0, "UpdateTime": now_ms()}


def mopup_reward(goods, amount, run, index=0):
    return apidefaults.default("RewardContents", GoodsType=goods, Count=run, ContentsIndex=index,
                               ContentsCount=amount)


def gained_items(contents):
    """RewardItemList for the mop-up's item rewards: the amounts gained, one entry per item."""
    gained = {}
    for c in contents:
        if c["GoodsType"] == ITEM_GOODS:
            gained[c["ContentsIndex"]] = gained.get(c["ContentsIndex"], 0) + c["ContentsCount"]
    return [{"ItemIndex": k, "Qty": n, "Lock": 0, "UpdateTime": now_ms()} for k, n in gained.items()]


@api("questEvent/questEventMopUp")
def quest_event_mop_up(req):
    log_story("questEventMopUp", req)
    index = int(req.get("QuestEventStageIndex") or 0)
    row = quest_event_stage_row(index)
    ap = row.get("activePointValue", 0)
    with _lock:
        state = load_state()
        runs, ticket = mopup_runs(state, req)
        spend_ap(state, ap * runs)
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before + QUEST_EVENT_EXP_PER_AP * ap * runs
        entry = state.setdefault("questEventStages", {}).setdefault(str(index), {"result": 0, "plays": 0, "clears": 0})
        entry["plays"] += runs
        entry["clears"] += runs
        today = daily(state).setdefault("questEventClears", {})
        today[str(index)] = today.get(str(index), 0) + runs
        pot = gold_pot(row)       # the Gold Dungeon: a full run's gold too (a played run pays the gold it gained)
        contents = []
        for run in range(1, runs + 1):
            count_play(state, "exp")
            clear = give_rewards(state, row.get("questEventStageClearRewardGroup", 0))[0]
            if pot:
                wallet = state.setdefault("money", dict(START_MONEY))
                wallet["Gold"] = wallet.get("Gold", 0) + pot
                gold = next((c for c in clear if c["GoodsType"] == GOLD_GOODS), None)
                if gold:          # one gold entry per run on the AUTO-CLEAR RESULT
                    gold["ContentsCount"] += pot
                else:
                    clear.append(reward(GOLD_GOODS, pot))
            contents += [mopup_reward(c["GoodsType"], c["ContentsCount"], run, c["ContentsIndex"]) for c in clear]
        rank_up, rank_rewards = apply_rank_up(state, before)
        completed = announce_quests(state)
        save_state(state)
    # the team (unchanged): without it the fighters' CP on QUEST INFO went blank after the AUTO-CLEAR
    return ok(QuestEventStageIndex=index, RewardContentsList=contents, RewardItemList=gained_items(contents),
              MopupTicketItem=ticket, AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple",
                                    start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              AccountLevelUpFlag=rank_up, AccountLevelUpRewardList=rank_rewards,
              QuestEvent=apidefaults.default("QuestEventWEBData", QuestEventIndex=row.get("questEventIndex", 0)),
              QuestEventStage=quest_event_stage(state, row) if row else apidefaults.default("QuestEventStageWEBData"),
              CompleteQuestList=completed)


# ---------------------------------------------------------------- TOWER OF TRIALS (client "CrucibleTower")
# recon/crucibletower_client.md: floors are QuestEventStageTable rows of questEventIndex 106 chained by openValue (a floor
# opens when openValue == the last cleared floor). Save state "crucibleTower" {lastClear, mopupMs, mopupCount}; the
# challenges used today are daily(state)["crucibleTower"]. One skip a server day pays every cleared floor's skip reward.
TOWER_EVENT = 106
TOWER_DEFAULT_CHALLENGES = 3      # ConfigTable 401 (CrucibleTowerCount), the client's default 3 ("Challenge 3 / 3")


def tower_state(state):
    return state.setdefault("crucibleTower", {"lastClear": 0, "mopupMs": 0, "mopupCount": 0})


def tower_challenges_left(state):
    top = next((int(r.get("value1") or 0) for r in table_rows("ConfigTable") if r["configIndex"] == 401),
               TOWER_DEFAULT_CHALLENGES)
    return max(0, top - daily(state).get("crucibleTower", 0))


def tower_day(ms):
    return time.strftime("%Y%m%d", time.localtime(ms / 1000 - SOUL_RESET_HOUR * 3600))


@api("questEvent/crucibleTowerInfo")
def crucible_tower_info(req):
    log_story("crucibleTowerInfo", req)
    with _lock:
        state = load_state() or {}
        tower = tower_state(state)
        return ok(CrucibleTower={"StageIndex": tower["lastClear"], "LastClearStageIndex": tower["lastClear"],
                                 "MopupTime": tower["mopupMs"], "ChallengePoint": tower_challenges_left(state),
                                 "RegTime": now_ms(), "mopupCount": tower["mopupCount"]})


@api("questEvent/crucibleTowerStart")
def crucible_tower_start(req):
    log_story("crucibleTowerStart", req)
    index = int(req.get("QuestEventStageIndex") or 0)
    row = quest_event_stage_row(index)
    token = now_ms()
    with _lock:
        state = load_state()
        if row.get("questEventIndex") != TOWER_EVENT or int(row.get("openValue") or 0) != tower_state(state)["lastClear"]:
            return {"ResultCode": 1, "ResultMessage": "floor not open"}
        if tower_challenges_left(state) <= 0:
            return {"ResultCode": 1, "ResultMessage": "no challenges left"}
        # no AP is spent; the challenge is spent only on a loss (crucible_tower_end)
    return ok(AccountMoney=money(state), QuestEventPlayToken=token,
              **{k: req.get(k) for k in ("StrikerType", "StrikerUsn", "StrikerIndex", "StrikerGameDb", "StrikerNickName")
                 if req.get(k) not in (None, "")})


@api("questEvent/crucibleTowerEnd")
def crucible_tower_end(req):
    log_story("crucibleTowerEnd", req)
    index, result = int(req.get("QuestEventStageIndex") or 0), int(req.get("BattleResult") or 0)
    row, won = quest_event_stage_row(index), result == WIN
    with _lock:
        state = load_state()
        tower = tower_state(state)
        first = won and index > tower["lastClear"]
        clear = []
        if won:
            clear = give_rewards(state, row.get("questEventStageClearRewardGroup", 0))[0]
            if first:     # raised only when higher; the first clear's prizes ride in ClearRewardList (no other list is read)
                clear += give_rewards(state, row.get("questEventStageFirstClearRewardGroup", 0))[0]
                tower["lastClear"] = index
        d = daily(state)
        d["tower"] = d.get("tower", 0) + 1       # mission 9015 "Play the Tower of Trials", won or lost
        if not won:   # real: "Challenge 2 / 3" stayed through six wins (video, recon/crucibletower_real.md); a loss spends one
            d["crucibleTower"] = d.get("crucibleTower", 0) + 1
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before
        rank_up, rank_rewards = apply_rank_up(state, before)
        completed = announce_quests(state)
        save_state(state)
    return ok(QuestEventStageIndex=index, BattleResult=result, AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple", start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              RewardItemList=gained_items(clear), ClearRewardList=clear,
              AccountLevelUpFlag=rank_up, AccountLevelUpRewardList=rank_rewards,
              RewardComedown=None, RemainItem=None, CompleteQuestList=completed)


@api("questEvent/crucibleTowerMopUp")
def crucible_tower_mop_up(req):
    log_story("crucibleTowerMopUp", req)
    now = now_ms()
    with _lock:
        state = load_state()
        tower = tower_state(state)
        if tower["lastClear"] <= 0 or (tower["mopupMs"] and tower_day(tower["mopupMs"]) == tower_day(now)):
            return {"ResultCode": 1, "ResultMessage": "no skip left"}     # AdsResultFlag is ignored: no ads offline
        total = {}      # every cleared floor's skip reward, merged per (goods, item)
        for r in table_rows("QuestEventStageTable"):
            if r.get("questEventIndex") == TOWER_EVENT and r["questEventStageIndex"] <= tower["lastClear"]:
                for c in reward_contents(r.get("questEventCrucibleTowerClearRewardGroup", 0)):
                    key = (c["GoodsType"], c["ContentsIndex"])
                    total[key] = total.get(key, 0) + c["ContentsCount"]
        paid = []
        for (goods, item), amount in total.items():
            if goods in (GOLD_GOODS, RUBY_GOODS, 3):      # the merged goods go straight to the wallet / inventory
                wallet = regen_ap(state)
                key = {GOLD_GOODS: "Gold", RUBY_GOODS: "Cash", 3: "ActivePoint"}[goods]
                wallet[key] = int(wallet.get(key, 0)) + amount
            elif goods == ITEM_GOODS:
                inv = items(state)
                inv[str(item)] = int(inv.get(str(item), 0)) + amount
            paid.append(mopup_reward(goods, amount, 1, item))
        tower["mopupMs"], tower["mopupCount"] = now, tower["mopupCount"] + 1
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before
        rank_up, rank_rewards = apply_rank_up(state, before)
        completed = announce_quests(state)
        save_state(state)
    return ok(QuestEventStageIndex=int(req.get("QuestEventStageIndex") or 0), RewardContentsList=paid,
              RewardItemList=gained_items(paid), AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple", start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              AccountLevelUpFlag=rank_up, AccountLevelUpRewardList=rank_rewards, AdsList=[],
              CompleteQuestList=completed)


@api("adventure/stageMopUp")
def adventure_stage_mop_up(req):
    log_story("stageMopUp", req)
    index = int(req.get("StageIndex") or 0)
    row = next((r for r in table_rows("StageTable") if r["stageIndex"] == index), {})
    soul = SOUL_ITEM_BASE + SOUL_ITEM_FIGHTER[index] if index in SOUL_ITEM_FIGHTER else 0
    gold = STAGE_GOLD.get(index, CLEAR_GOLD)
    with _lock:
        state = load_state()
        runs, ticket = mopup_runs(state, req)
        spend_ap(state, row.get("activePointValue", 0) * runs)
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before + STORY_ACCOUNT_EXP_OF.get(index, STORY_ACCOUNT_EXP) * runs
        entry = state.setdefault("stages", {}).setdefault(str(index), {"result": 0, "plays": 0})
        entry["plays"] += runs
        wallet, inv, contents = regen_ap(state), items(state), []
        for run in range(1, runs + 1):
            count_play(state, "soul" if soul else "story")
            wallet["Gold"] = wallet.get("Gold", 0) + gold
            contents.append(mopup_reward(GOLD_GOODS, gold, run))
            if soul:      # a soul event run: today's entries and the boss's souls
                if entry.get("day") != soul_day():
                    entry["day"], entry["today"] = soul_day(), 0
                entry["today"] = entry.get("today", 0) + 1
                inv[str(soul)] = int(inv.get(str(soul), 0)) + SOUL_DROPS
                contents.append(mopup_reward(ITEM_GOODS, SOUL_DROPS, run, soul))
        fighter_exp = STORY_FIGHTER_EXP.get(index, STORY_FIGHTER_EXP_DEFAULT) * runs
        for c in req.get("CharacterList") or []:
            if c.get("CharacterIndex"):
                fighter = character_state(state, int(c["CharacterIndex"]))
                fighter["exp"] = max(fighter.get("exp", 0), int(c.get("Exp", 0))) + fighter_exp
        rank_up, rank_rewards = apply_rank_up(state, before)
        completed = announce_quests(state)
        save_state(state)
    # SoulDropEventStage sets a soul stage's entries used today on the client (null / StageIndex 0: nothing)
    soul_stage = apidefaults.default("SoulDropEventStage", SeriesIndex=row.get("seriesGroup", 0), StageIndex=index,
                                     Chapter=row.get("chapter", 0), StageDifficulty=row.get("difficultyType", 0),
                                     PlayCount=plays_today(entry), BattleResult=1, TodayDate=now_ms()) if soul else None
    return ok(StageIndex=index, RewardContentsList=contents, RewardItemList=gained_items(contents),
              MopupTicketItem=ticket, AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=[simple(character_state(state, int(c["CharacterIndex"])), "CharacterSimple",
                                    start_grades())
                             for c in req.get("CharacterList") or [] if c.get("CharacterIndex")],
              AccountLevelUpFlag=rank_up, AccountLevelUpRewardList=rank_rewards, SoulDropEventStage=soul_stage,
              CompleteQuestList=completed)


# ---------------------------------------------------------------- fighter growth
# The client works out the result (new exp, grade, limit break phase/progress, enchant) from the tables and sends
# it with what it spent; offline we apply it. Requests are also appended to logs/growth-requests.log.
GROWTH_LOG = os.path.join(HERE, "logs", "growth-requests.log")


def log_growth(name, req):
    os.makedirs(os.path.dirname(GROWTH_LOG), exist_ok=True)
    with open(GROWTH_LOG, "a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%H:%M:%S')} {name} {json.dumps(req, ensure_ascii=False)[:4000]}\n")


def fighter_level(index, exp):
    """The client's own rule (CharacterLevelingTable.GetCharacterLevel): the first row whose cumulative
    exp<levelingType> is above the fighter's exp; equal means the next level."""
    kind = next((r.get("levelingType", 1) for r in table_rows("CharacterTable") if r["characterIndex"] == index), 1)
    rows = sorted(table_rows("CharacterLevelingTable"), key=lambda r: r["chracterLevel"])
    for r in rows:
        need = r.get(f"exp{kind}", 0)
        if exp == need:
            return r["chracterLevel"] + 1
        if exp < need:
            return r["chracterLevel"]
    return rows[-1]["chracterLevel"] if rows else 1


def simple(c, cls, start=None):
    """CharacterSimple* reply for a fighter's saved progress (only the fields that class has)."""
    full = character(c, start)
    full.update(CharacterLevel=fighter_level(c["index"], c.get("exp", 0)))
    fields = {f[0] for f in apidefaults.CLASSES.get(cls, [])}
    return apidefaults.default(cls, **{k: v for k, v in full.items() if k in fields})


def growth_request(name, req, apply):
    """Apply one growth action to the saved fighter -> (state, fighter, used item numbers) or an error reply."""
    log_growth(name, req)
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        ch = req.get("Character") or {}   # the awakening requests name the fighter at the top level
        c = character_state(state, int(ch.get("CharacterIndex") or req.get("CharacterIndex") or 0))
        used = apply(state, c, ch, req)
        save_state(state)
    return state, c, used


def spend_gold(state, n):
    m = state.setdefault("money", {})
    m["Gold"] = max(0, money(state)["Gold"] - int(n or 0))


@api("character/characterLevelUp")
def character_level_up(req):
    def apply(state, c, ch, req):
        c["exp"] = max(int(c.get("exp", 0)) + int(req.get("AddExp", 0) or 0), int(ch.get("Exp", 0) or 0))
        c["level"] = int(ch.get("CharacterLevel", 0) or c.get("level", 0))
        used = use_items(state, req.get("ItemList"))
        if used:   # EXP capsules used (growth mission "Use a Fighter EXP Capsule")
            counters = state.setdefault("counters", {})
            counters["expCapsule"] = counters.get("expCapsule", 0) + 1
        return used
    r = growth_request("characterLevelUp", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(LevelUpSuccess=1, ItemList=item_list(state, used), Character=simple(c, "CharacterSimple", start_grades()),
              CompleteQuestList=announce_quests(state))


# ---------------------------------------------------------------- quests (growth missions, tools/gen_quest.py)
# The server works out each quest's progress from the save (quest_progress); the client derives the state
# (QuestBase.UpdateCondition): no entry = not started, ProcessCount < CompleteCount = in progress, reached with
# RewardGiveTime 0 = claimable, RewardGiveTime set = done. Claimed quests: save.json "questRewards" {quest: time}.
# Quests whose completion the client was told about (its "mission complete" notice, CompleteQuestList in any
# reply): "questsAnnounced".
GROWTH_QUEST = 3000
DAILY_QUEST, ACHIEVEMENT_QUEST = 1, 2       # the Mission screen's DAILY and ACHIEVEMENT tabs (tools/gen_quest.py)
ANNOUNCED_TYPES = (GROWTH_QUEST, DAILY_QUEST, ACHIEVEMENT_QUEST)
NO_EXPIRY = 4102444800000   # 2100-01-01
DAILY_RESET_HOUR = 5        # SessionStartResponse.DailyResetHour: daily missions, points and soul entries reset


def daily(state):
    """Today's daily record (save.json "daily"): counters, claimed daily missions, points and point chests,
    announced daily missions; a new one after DAILY_RESET_HOUR."""
    d = state.get("daily")
    if not d or d.get("day") != soul_day():
        d = state["daily"] = {"day": soul_day(), "story": 0, "soul": 0, "claims": {}, "points": 0, "chests": [],
                              "announced": []}
    return d


def next_reset_ms():
    t = time.time()
    day_start = time.mktime(time.strptime(soul_day(), "%Y%m%d")) + DAILY_RESET_HOUR * 3600
    while day_start <= t:
        day_start += 86400
    return int(day_start * 1000)


def count_play(state, kind):
    """A story stage (kind "story"), soul event ("soul") or EXP dungeon run ("exp") played: today's and the total
    counters of the missions."""
    d = daily(state)
    d[kind] = d.get(kind, 0) + 1
    if kind == "exp":
        return
    counters = state.setdefault("counters", {})
    if "storyPlays" not in counters:   # saves from before the counter (this play is already in stages)
        counters["storyPlays"] = sum(e.get("plays", 0) for e in state.get("stages", {}).values()) - 1
    counters["storyPlays"] += 1


def quest_point(state):
    """QuestPointInfo of the daily points: points today, chests claimed (comma list), when they reset."""
    d = daily(state)
    return {"questPointIndex": 1, "questPoint": d.get("points", 0),
            "questPointRewardIndexList": ",".join(str(c) for c in d.get("chests", [])), "expireTime": next_reset_ms()}


def quest_rows():
    return {r["questIndex"]: r for r in table_rows("QuestTable")}


def quest_progress(state, row):
    """(done, needed) for a quest by its completeTermsType (gen_quest.py lists the rules)."""
    kind, v1, v2 = (row.get("completeTermsType", 0), row.get("completeTermsTypeValue1", 0),
                    row.get("completeTermsTypeValue2", 0))
    stages = state.get("stages", {})
    cleared = lambda i: stages.get(str(i), {}).get("result", 0) > 0
    if kind == 3:          # StoryModeStageClear
        return int(cleared(v1)), 1
    if kind == 4:          # StoryModeStageClearCheck: every battle stage of a chapter (as many as its 9 stars
        battle = [r["stageIndex"] for r in table_rows("StageTable") if r.get("chapter") == v1   # need, even while
                  and r.get("stageType") == 2]                                                # some aren't built)
        stars_max = next((c.get("chapterStageMaxValue", 0) for c in table_rows("ChapterTable") if c["chapter"] == v1), 0)
        return sum(cleared(s) for s in battle), max(1, len(battle), stars_max // 3)
    if kind == 16:         # UserRank
        return min(account_level(state.get("exp", 0)), v1), v1
    if kind == 24:         # ClearGroupQuest: the tab's missions claimed
        tab = [r["questIndex"] for r in table_rows("GrowthMissionGroupTable") if r.get("growthMissionGroup") == v1
               and r.get("growthMissionPages") == v2 and r.get("growthMissionType") == 1]
        claimed = state.get("questRewards", {})
        return sum(1 for q in tab if str(q) in claimed), max(1, len(tab))
    if kind == 9001:       # fighters in one team deck
        best = max((sum(1 for c in d["chars"] if c) for d in state.get("decks", [])), default=0)
        return min(best, v1), v1
    if kind == 9002:       # EXP capsule uses
        return min(state.get("counters", {}).get("expCapsule", 0), v1), v1
    if kind == 9003:       # a fighter at this level
        best = max((fighter_level(c["index"], c.get("exp", 0)) for c in state.get("characters", [])), default=1)
        return min(best, v1), v1
    if kind == 9010:       # opened the game today
        return 1, 1
    if kind in (9011, 9012, 9014):   # story stages / soul events / EXP dungeon runs played today
        return min(daily(state).get({9011: "story", 9012: "soul", 9014: "exp"}[kind], 0), v1), v1
    if kind == 9015:       # Tower of Trials plays today
        return min(daily(state).get("tower", 0), v1), v1
    if kind == 9016:       # EXCITING ROULETTE spins today
        return min(daily(state).get("roulette", {}).get(str(ROULETTE_MISSION_GROUP), 0), v1), v1
    if kind == 9017:       # story stages played in total (saves from before the counter: their stages' plays)
        plays = state.get("counters", {}).get("storyPlays")
        if plays is None:
            plays = sum(e.get("plays", 0) for e in state.get("stages", {}).values())
        return min(plays, v1), v1
    if kind == 9019:       # fighters owned
        return min(len(owned_characters(state)), v1), v1
    if kind == 9013:       # Secret Shop purchases today
        return min(daily(state).get("secretShop", 0), v1), v1
    return 0, max(1, v1)   # 101 guild, 9018 cards: not offline yet


def claims(state, row):
    """Where a quest's claim is kept: today's record for daily missions, "questRewards" for the others."""
    if row.get("questType") == DAILY_QUEST:
        return daily(state).setdefault("claims", {})
    return state.setdefault("questRewards", {})


def quest_entry(state, row):
    done, need = quest_progress(state, row)
    is_daily = row.get("questType") == DAILY_QUEST
    return {"QuestIndex": row["questIndex"], "QuestType": row.get("questType", 0), "CompleteCount": need,
            "ProcessCount": done, "AccumulateCount": done, "UpdateTime": now_ms(), "CreateTime": state["created"],
            "RewardGiveTime": claims(state, row).get(str(row["questIndex"]), 0),
            "ExpireTime": next_reset_ms() if is_daily else NO_EXPIRY,
            "RepeatCycle": 0, "RepeatCount": 0, "FestivalEventIndex": 0, "EpicOpenTermStageIndex": 0,
            "EpicEpisodeIndex": 0, "EpicChapterIndex": 0, "QuestCountType": 0, "RandomTermsType": 0,
            "RandomTermsValue": 0}


def locked_growth_quests(state):
    """Quests of growth tabs not open yet: tab n opens once tab n-1's big reward (its PageClear quest) was claimed.
    The client shows a tab whose quests it doesn't know as locked, and opens the popup on the last known tab."""
    groups = table_rows("GrowthMissionGroupTable")
    page_quest = {(r["growthMissionGroup"], r["growthMissionPages"]): r["questIndex"] for r in groups
                  if r.get("growthMissionType") == 2}
    claimed = state.get("questRewards", {})
    return {r["questIndex"] for r in groups if r["growthMissionPages"] > 1
            and str(page_quest.get((r["growthMissionGroup"], r["growthMissionPages"] - 1))) not in claimed}


def quest_list(state, quest_type=GROWTH_QUEST, only=None):
    locked = locked_growth_quests(state) if quest_type == GROWTH_QUEST else set()
    return [quest_entry(state, r) for q, r in sorted(quest_rows().items())
            if r.get("questType") == quest_type and (not only or q in only) and q not in locked]


def announce_quests(state, kinds=ANNOUNCED_TYPES):
    """Quests that became complete since the client last heard: CompleteQuestList (call inside the save lock, then
    save the state)."""
    new = []
    for kind in kinds:
        told = daily(state)["announced"] if kind == DAILY_QUEST else state.setdefault("questsAnnounced", [])
        fresh = [e for e in quest_list(state, kind) if e["ProcessCount"] >= e["CompleteCount"]
                 and not e["RewardGiveTime"] and e["QuestIndex"] not in told]
        told += [e["QuestIndex"] for e in fresh]
        new += fresh
    return new


def claimable(state):
    """Missions done and not claimed yet (the lobby's mission red dot)."""
    return [e for kind in ANNOUNCED_TYPES for e in quest_list(state, kind)
            if e["ProcessCount"] >= e["CompleteCount"] and not e["RewardGiveTime"]]


def reward_contents(group):
    """A RewardGroupTable group as RewardContents, without paying it (what give_rewards would list)."""
    return [reward(r.get("rewardType", 0), r.get("contentsCountMin", 0),
                   r.get("contentsIndex", 0) if r.get("rewardType") == ITEM_GOODS else 0)
            for r in table_rows("RewardGroupTable")
            if r.get("rewardGroup") == group and r.get("rewardType") in (GOLD_GOODS, RUBY_GOODS, 3, ITEM_GOODS)]


def give_rewards(state, group):
    """Pay a RewardGroupTable group -> (QuestRewardList, items, fighters). rewardType is a GoodsType (1 gold, 2 rubies,
    3 AP, 11 fighter, 13 item), contentsIndex the item or fighter."""
    contents, item_ids, fighters = [], [], []
    wallet = regen_ap(state)
    for r in table_rows("RewardGroupTable"):
        if r.get("rewardGroup") != group:
            continue
        kind, index, count = r.get("rewardType", 0), r.get("contentsIndex", 0), r.get("contentsCountMin", 0)
        if kind in (GOLD_GOODS, RUBY_GOODS, 3):
            key = {GOLD_GOODS: "Gold", RUBY_GOODS: "Cash", 3: "ActivePoint"}[kind]
            wallet[key] = int(wallet.get(key, 0)) + count
            contents.append(reward(kind, count))
        elif kind == ITEM_GOODS:
            if index in HOE_ELEMENTS:      # the Hall of Elements "memory markers": a random Memory of the element
                index = hoe_memory(HOE_ELEMENTS[index])
                if not index:
                    continue
            inv = items(state)
            inv[str(index)] = int(inv.get(str(index), 0)) + count
            item_ids.append(index)
            contents.append(reward(ITEM_GOODS, count, index))
        elif kind == 11:   # fighter: only in RewardCharacterList (the client lists both lists in its reward popup)
            fighters.append(give_fighter(state, index, r.get("contentsGrade", 0) or 0))
    return contents, item_ids, fighters


SOUL_ITEM_BASE = 200000                     # a fighter's soul = item 200000 + fighter (tools/gen_roster.py)
DUPLICATE_SOULS = {3: 10, 4: 20, 5: 50, 6: 100}   # souls for a fighter the account already has (ours)


def owns(state, index):
    """Saved, or auto-owned while ownAllFighters -- never a Prove NPC boss: no reward may grant one, so it
    must not resolve as an owned duplicate either (give_fighter would mint its souls)."""
    return (state.get("ownAllFighters", True) and index not in npc_fighter_indexes()) \
        or any(c["index"] == index for c in state["characters"])


def give_fighter(state, index, grade):
    """A fighter reward: a new fighter joins; one already owned turns into its souls (CharacterReward
    ExCharacterSoul / ExCharacterSoulQty, which the reward popup shows as "Soul: <name> xN")."""
    if owns(state, index):
        soul, qty = SOUL_ITEM_BASE + index, DUPLICATE_SOULS.get(grade, 10)
        inv = items(state)
        inv[str(soul)] = int(inv.get(str(soul), 0)) + qty
        return apidefaults.default("CharacterReward", CharacterIndex=index, Grade=grade, ExCharacterSoul=soul,
                                   ExCharacterSoulQty=qty)
    c = character_state(state, index)
    c["grade"] = max(c.get("grade", 3), grade)
    return apidefaults.default("CharacterReward", CharacterIndex=index, Grade=c["grade"], Exp=c.get("exp", 0))


def claim_quests(indexes):
    """quest/reward and quest/rewardAll: pay each completed, unclaimed quest once."""
    with _lock:
        state = load_state()
        rows = quest_rows()
        contents, item_ids, fighters, claimed = [], [], [], []
        for q in indexes:
            row = rows.get(q)
            if not row or str(q) in claims(state, row):
                continue
            done, need = quest_progress(state, row)
            if done < need:
                continue
            claims(state, row)[str(q)] = now_ms()
            if row.get("pointValue"):      # a daily mission pays its points (shown as the point item)
                daily(state)["points"] = daily(state).get("points", 0) + row["pointValue"]
            c, i, f = give_rewards(state, row.get("questRewardGroup", 0))
            contents += c
            item_ids += i
            fighters += f
            claimed.append(q)
        announced = announce_quests(state)
        save_state(state)
    entries = [quest_entry(state, rows[q]) for q in claimed]
    return state, entries, dict(
        AccountMoney=money(state), PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state.get("exp", 0)),
        RewardCharacterList=fighters, RewardItemList=item_list(state, item_ids), QuestRewardList=contents,
        CompleteQuestList=announced, ServerUtcTime=now_ms(), questPoint=quest_point(state),
        # null unless they apply: Parse_QuestReward writes non-null guild objects into the guild's data (none ->
        # exception) and looks a non-null NextQuest up in QuestTable (a defaulted quest 0 isn't there -> exception)
        GuildQuestReward=None, GuildLevelInfo=None, NextQuest=None)


# ---------------------------------------------------------------- mailbox (recon/story/missions_mailbox.md)
# GIFTBOX mails live in save.json "posts" until collected. A mail's text is its PostTypeTable row
# (tools/gen_quest.py). Video 4: "Friendship Point x20 - A reward for using a Support." after each run with a supporter.
POST_SUPPORT = 1                      # PostTypeTable code: "A reward for using a Support."
POST_DAYS = 30                        # mails expire after 30 days (video 4: "29 Day(s)" left)
POST_CATEGORY = {11: 1, 12: 2, 13: 3}  # GoodsType -> PostCategory (fighter, battle card, item); the rest 4 ETC.
FRIEND_POINT_GOODS = 5
FRIEND_POINT_CAP = 10000
SUPPORT_POINTS_CONFIG = {1: 702, 2: 701, 3: 703, 5: 703}   # supporter type -> ConfigTable row of its friendship points


def send_post(state, post_type, goods, count, index=0, message="", grade=0):
    no = state.get("postNo", 0) + 1
    state["postNo"] = no
    state.setdefault("posts", []).append({"no": no, "type": post_type, "goods": goods, "index": index,
                                          "count": count, "message": message, "created": now_ms(), "grade": grade})


def live_posts(state):
    return [p for p in state.get("posts", []) if p["created"] + POST_DAYS * 86400000 > now_ms()]


def post_entry(p):
    return apidefaults.default("Post", PostNo=p["no"], PostType=p["type"],
                               PostCategory=POST_CATEGORY.get(p["goods"], 4), GoodsType=p["goods"],
                               ContentsIndex=p["index"], ContentsGrade=p.get("grade", 0), ContentsCount=p["count"],
                               Message=p.get("message", ""),
                               CreateTime=p["created"], ExpireTime=p["created"] + POST_DAYS * 86400000)


@api("post/postList")
def post_list(req):
    state = load_state()
    category = int(req.get("PostCategory") or 0)
    posts = live_posts(state) if state else []
    of = lambda c: [p for p in posts if c == 0 or POST_CATEGORY.get(p["goods"], 4) == c]
    return ok(PostCategory=category, PostList=[post_entry(p) for p in of(category)],
              PostCountList=[{"PostCategory": c, "PostCount_": len(of(c))} for c in range(5)])


@api("post/postRead")
def post_read(req):
    """COLLECT / COLLECT ALL: pay the mails' goods and remove them."""
    with _lock:
        state = load_state()
        wanted = {int(n) for n in req.get("PostNoList") or []}
        wallet = regen_ap(state)
        item_ids, fighters, read = [], [], []
        for p in live_posts(state):
            if p["no"] not in wanted:
                continue
            goods, count = p["goods"], p["count"]
            key = {GOLD_GOODS: "Gold", RUBY_GOODS: "Cash", 3: "ActivePoint", FRIEND_POINT_GOODS: "FriendPoint"}.get(goods)
            if key == "FriendPoint":   # the guides: friendship points stop at 10,000; a mail over the cap loses the rest
                wallet[key] = min(FRIEND_POINT_CAP, int(wallet.get(key, 0)) + count)
            elif key:
                wallet[key] = int(wallet.get(key, 0)) + count
            elif goods == ITEM_GOODS:
                inv = items(state)
                inv[str(p["index"])] = int(inv.get(str(p["index"]), 0)) + count
                item_ids.append(p["index"])
            elif goods == 11:
                fighters.append(give_fighter(state, p["index"], p.get("grade", 0)))
            read.append(p["no"])
        state["posts"] = [p for p in state.get("posts", []) if p["no"] not in read]
        save_state(state)
    return ok(PostNoList=read, ReadTime=now_ms(), AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state.get("exp", 0)),
              RewardItemList=item_list(state, item_ids), RewardCharacterList=fighters)


# ---------------------------------------------------------------- CHECK-IN LOG (tools/gen_checkin.py)
# Each tab (EventAttendanceTable row) counts the days the account signed in (GiveTime) and the days paid
# (LastGiveTime); the first attendance/info of a day (after DAILY_RESET_HOUR) adds a day, showing the tab sends
# attendance/give and the day's reward goes to the mailbox (video 5: "Rewards obtained from <tab> Check-in." mails).
# A tab with attendanceRepeat 1 (Every Day) starts over after its last day; the others stop (the client closes them).
# save.json "attendance": {tab: {"days", "paid", "day" (YYYYMMDD of the last check-in), "reg" (ms)}}.
ATTENDANCE_POSTS = {1: 2, 2: 3, 3: 4}     # tab -> PostTypeTable code (tools/gen_quest.py)
PROGRESS_TAB = 4                          # tools/gen_progress.py: the preservation progress banner (OURS)


def attendance_tabs():
    return {r["eventAttendanceIndex"]: r for r in table_rows("EventAttendanceTable")}


def attendance_entry(index, row, e):
    return apidefaults.default("AttendanceReward", AttendanceRewardGroup=row.get("attendanceRewardGroup", 0),
                               GiveTime=e["days"], LastGiveTime=e["paid"], RegDate=e["reg"],
                               RewardGetFlag=1 if e["paid"] >= e["days"] else 0,
                               AttendanceIndex=index)


def attendance_check_in(state):
    """Today's check-in on every tab that still has days (repeating tabs start a new round)."""
    book, today = state.setdefault("attendance", {}), soul_day()
    for index, row in attendance_tabs().items():
        e = book.setdefault(str(index), {"days": 0, "paid": 0, "day": "", "reg": now_ms()})
        if index == PROGRESS_TAB:          # the login banner: a waiting day at every sign-in
            # GiveTime 1 != LastGiveTime 2: the client's IsAllGetRewardsComplete (GiveTime == LastGiveTime) stays off,
            # so the CHECK-IN LOG opens on it, but no day waits (GiveTime > LastGiveTime), so no claim and no
            # "Rewards obtained" popup (user 2026-11-12: "remove this gold rewards popup ... keep the banner")
            e.update(days=1, paid=2, day=today)
            continue
        total = row.get("evnetAttendanceDayCount", 0)
        if e["day"] == today:
            continue
        if e["days"] >= total and e["paid"] >= total and row.get("attendanceRepeat") == 1:
            e["days"], e["paid"], e["reg"] = 0, 0, now_ms()
        if e["days"] < total:
            e["days"] += 1
            e["day"] = today
    return book


def attendance_list(state):
    tabs, book = attendance_tabs(), state.get("attendance", {})
    return [attendance_entry(index, tabs[index], book[str(index)]) for index in sorted(tabs) if str(index) in book]


@api("attendance/info")
def attendance_info(req):
    with _lock:
        state = load_state()
        if state is None:
            return {}
        attendance_check_in(state)
        save_state(state)
    return ok(EventAttendanceList=attendance_list(state))


@api("attendance/give")
def attendance_give(req):
    """Pay the checked-in days of the listed tabs into the mailbox."""
    log_story("attendanceGive", req)
    with _lock:
        state = load_state()
        tabs, book = attendance_tabs(), state.setdefault("attendance", {})
        for index in req.get("AttendanceIndexList") or []:
            index = int(index)
            e, row = book.get(str(index)), tabs.get(index)
            if not e or not row:
                continue
            days = {r["giveTime"]: r for r in table_rows("AttendanceRewardGroupTable")
                    if r.get("attendanceRewardGroup") == row.get("attendanceRewardGroup")}
            for day in range(e["paid"] + 1, e["days"] + 1):
                r = days.get(day)
                if r and r.get("contentsCount"):          # the banner tab's day is empty: no mail
                    send_post(state, ATTENDANCE_POSTS.get(index, 2), r.get("rewardType", 0), r.get("contentsCount", 0),
                              r.get("contentsIndex", 0), grade=r.get("contentsGrade", 0))
            e["paid"] = e["days"]
        save_state(state)
    return ok(EventAttendanceList=attendance_list(state))


# ---------------------------------------------------------------- ROULETTE (tools/gen_roulette.py)
# Video 5's EXCITING ROULETTE (group 1, always open) and FIGHTER GROWTH SUPPORT ROULETTE (group 2, in weekly rounds:
# "6 Day(s) remaining"). player/poll lists their schedules (category 23, SubGroup = the group), which puts them among
# the lobby's top-right event icons (EventDataTable). START spends the group's ticket and drops a prize (weighted by
# RouletteRewardTable) into the first empty BINGO slot; the reply names it and the wheel stops on its wedge. "Receive"
# mails a slot ("A Roulette Event Reward.", the video's mailbox); three alike go out together, doubled ("Complete
# Bingo to double the rewards!"). save.json "roulette": {group: 3 slots, each [GoodsType, index, amount] or null};
# today's spins in daily()["roulette"] ("Remaining 999/999").
ROULETTE_CATEGORY = 23               # EOperateCategory.Roulette
ROULETTE_ALWAYS = (1,)               # groups without an end (the lobby shows no time left for them)
ROULETTE_ROUND_DAYS = 7              # the others: Monday (after DAILY_RESET_HOUR) to Monday
TIMED_SCHEDULE, NO_END = 2, 4102444800   # OpsDefines.TIME_SCHEDULE_FALG; 2100-01-01 (unix s)
ROULETTE_MISSION_GROUP = 1           # "[DAILY] Play Exciting Roulette 1 time(s)" (quest 310007, kind 9016)
POST_ROULETTE = 5                    # PostTypeTable code (tools/gen_quest.py)
ROULETTE_SLOTS = 3


def roulette_groups():
    return {r["rouletteGroupIndex"]: r for r in table_rows("RouletteGroupTable")}


def roulette_schedule(group):
    return next((r for r in table_rows("RouletteScheduleTable")
                 if r.get("rouletteGroup") == group and not r.get("rouletteLevel")), None)


def roulette_round(group):
    """(start, end) of the group's current round in unix seconds."""
    if group in ROULETTE_ALWAYS:
        return 0, NO_END
    day = time.mktime(time.strptime(soul_day(), "%Y%m%d")) + DAILY_RESET_HOUR * 3600
    start = day - time.localtime(day).tm_wday * 86400
    return int(start), int(start + ROULETTE_ROUND_DAYS * 86400)


def roulette_schedules():
    out = []
    for g in sorted(roulette_groups()):
        start, end = roulette_round(g)
        out.append(apidefaults.default("OperateSchedule", Version=1, Category=ROULETTE_CATEGORY, Index=g,
                                       Detail=apidefaults.default("OperateScheduleData", SubGroup=[g], StartTs=start,
                                                                  EndTs=end, OffOnSched=ALWAYS_OPEN
                                                                  if g in ROULETTE_ALWAYS else TIMED_SCHEDULE)))
    return out


def roulette_slots(state, group):
    return state.setdefault("roulette", {}).setdefault(str(group), [None] * ROULETTE_SLOTS)


def roulette_fields(state, group):
    """What RouletteEvent (info) and RouletteSlot (spin, receive) share: the slots and today's spins."""
    f = {"RouletteGroup": group, "RouletteIndex": (roulette_schedule(group) or {}).get("rouletteIndex", 0),
         "PlayCount": daily(state).get("roulette", {}).get(str(group), 0)}
    for n, slot in enumerate(roulette_slots(state, group), 1):
        f[f"ItemType{n}"], f[f"ItemIndex{n}"], f[f"ItemQty{n}"] = slot or (0, 0, 0)
    return f


def roulette_play_list(state):
    """The lobby icons' red dots: a ticket in hand and spins left today."""
    inv, spins = items(state), daily(state).get("roulette", {})
    return [{"RouletteGroup": g, "PlayCountExists": "true" if int(inv.get(str(r.get("rouletteNeedItemIndex")), 0))
             >= r.get("rouletteNeedItemValue", 1) and spins.get(str(g), 0) < r.get("limitDailyPlayRoulette", 0)
             else "false"} for g, r in sorted(roulette_groups().items())]


@api("event/rouletteInfo")
def roulette_info(req):
    group = int(req.get("rouletteGroup") or req.get("RouletteGroup") or 0)
    state, row, sched = load_state(), roulette_groups().get(group), roulette_schedule(group)
    if state is None or not row or not sched:
        return {}
    start, end = roulette_round(group)
    return ok(RouletteInfo=apidefaults.default(
        "RouletteEvent", **roulette_fields(state, group), EventStartTime=start * 1000, EventEndTime=end * 1000,
        EventRewardEndTime=end * 1000, RouletteDoubleBonus=sched.get("rouletteDoubleBonus", 0),
        RouletteTripleBonus=sched.get("rouletteTripleBonus", 0), RouletteBingoType=sched.get("rouletteBingoType", 0),
        RouletteNeedItemType=row.get("rouletteNeedItemType", 0), RouletteNeedItemIndex=row.get("rouletteNeedItemIndex", 0),
        RouletteNeedItemValue=row.get("rouletteNeedItemValue", 0),
        LimitDailyPlayRoulette=row.get("limitDailyPlayRoulette", 0)))


@api("event/roulettePlay")
def roulette_play(req):
    """START: a ticket for a prize in the first empty BINGO slot (the client checks ticket, slots and the daily
    limit before asking; an ad spin, AdsResultFlag, costs no ticket)."""
    log_story("roulettePlay", req)
    group = int(req.get("RouletteGroup") or 0)
    with _lock:
        state, row, sched = load_state(), roulette_groups().get(group), roulette_schedule(group)
        if state is None or not row or not sched:
            return {}
        slots, inv = roulette_slots(state, group), items(state)
        ticket, cost = str(row.get("rouletteNeedItemIndex", 0)), row.get("rouletteNeedItemValue", 1)
        free = bool(req.get("AdsResultFlag"))
        if None not in slots or (not free and int(inv.get(ticket, 0)) < cost):
            return {}
        wedges = [r for r in table_rows("RouletteRewardTable")
                  if r.get("rouletteRewardGroup") == sched.get("rouletteRewardGroup")]
        pick = random.choices(wedges, weights=[max(1, r.get("rouletteRewardItemRate", 0)) for r in wedges])[0]
        prize = [pick.get("rouletteRewardItemType", 0), pick.get("rouletteRewardItemIndex", 0),
                 pick.get("rouletteRewardItemValue", 0)]
        slots[slots.index(None)] = prize
        if not free:
            inv[ticket] = int(inv.get(ticket, 0)) - cost
        spins = daily(state).setdefault("roulette", {})
        spins[str(group)] = spins.get(str(group), 0) + 1
        save_state(state)
    return ok(RouletteSlot=apidefaults.default("RouletteSlot", **roulette_fields(state, group)),
              ItemList=item_list(state, [int(ticket)]), AccountMoney=money(state),
              RewardList=[reward(prize[0], prize[2], prize[1])], AdsList=[])


@api("event/rouletteRewardSlot")
def roulette_reward_slot(req):
    """Receive: one BINGO slot (SlotNo 1-3) to the mailbox."""
    log_story("rouletteRewardSlot", req)
    group, n = int(req.get("RouletteGroup") or 0), int(req.get("SlotNo") or 0) - 1
    with _lock:
        state = load_state()
        slots = roulette_slots(state, group)
        if 0 <= n < len(slots) and slots[n]:
            goods, index, amount = slots[n]
            send_post(state, POST_ROULETTE, goods, amount, index)
            slots[n] = None
        save_state(state)
    return ok(RouletteSlot=apidefaults.default("RouletteSlot", **roulette_fields(state, group)))


@api("event/rouletteRewardBonus")
def roulette_reward_bonus(req):
    """BINGO: three alike to the mailbox together, times the schedule's rouletteTripleBonus."""
    log_story("rouletteRewardBonus", req)
    group = int(req.get("RouletteGroup") or 0)
    with _lock:
        state = load_state()
        slots, sched = roulette_slots(state, group), roulette_schedule(group) or {}
        if all(slots) and all(s == slots[0] for s in slots):
            goods, index, amount = slots[0]
            send_post(state, POST_ROULETTE, goods, amount * len(slots) * max(1, sched.get("rouletteTripleBonus", 1)),
                      index)
            slots[:] = [None] * len(slots)
        save_state(state)
    return ok(RouletteSlot=apidefaults.default("RouletteSlot", **roulette_fields(state, group)))


@api("player/lobby")
def player_lobby(req):
    """Entering the lobby: today's missions done so far (the "[DAILY] Welcome." toast), the mission red dot
    (RedDotList "isQuestComplete", NetworkManagerWEB.TakeAndSetReddotList) and the daily points."""
    with _lock:
        state = load_state()
        if state is None:
            return {}
        announced = announce_quests(state)
        save_state(state)
    dots = [{"Key": "isQuestComplete", "Value": "true" if claimable(state) else "false"},
            {"Key": "isNewPostGet", "Value": "true" if live_posts(state) else "false"}]
    g = state.get("guild")
    guild = dict(MyGuildInfo=my_guild(state, g), GuildMemberInfo=[guild_member(state, g)],
                 GuildBuffList=guild_buffs(g)) if g else {}
    return ok(CompleteQuestList=announced, RedDotList=dots, questPointList=[quest_point(state)],
              RouletteEventPlayList=roulette_play_list(state), **guild)


@api("epicQuest/epicList")
def epic_quest_list(req):
    """Epic Quest episodes. The Mission screen asks for the Epic Daily tab's list only when the account has an
    episode (Controller_MissionBoard.RequestFirst_Step3) and draws nothing until that tab's list came back, so an
    empty list left it blank: one locked episode, as the video's "Can be used after unlocking Epic Quest Episode 0."."""
    return ok(EpicList=[{"EpicQuestIndex": 1, "State": 0}])


@api("quest/list")
def quest_list_api(req):
    state = load_state()
    only = {int(q) for q in req.get("ListQuestIndex") or [] if str(q).isdigit()}
    return ok(QuestList=quest_list(state, int(req.get("QuestType") or GROWTH_QUEST), only),
              questPointList=[quest_point(state)])


@api("quest/pointReward")
def quest_point_reward(req):
    """The daily point chests: pay each chest reached and not claimed today."""
    with _lock:
        state = load_state()
        d = daily(state)
        chests = {r["questPointRewardIndex"]: r for r in table_rows("QuestPointRewardTable")}
        contents, item_ids, fighters = [], [], []
        for c in req.get("questPointRewardIndexList") or []:
            row = chests.get(int(c))
            if not row or int(c) in d["chests"] or d.get("points", 0) < row.get("pointValue", 0):
                continue
            d["chests"].append(int(c))
            got = give_rewards(state, row.get("rewardGroupIndex", 0))
            contents += got[0]
            item_ids += got[1]
            fighters += got[2]
        save_state(state)
    return ok(AccountMoney=money(state), PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN,
                                                                           Exp=state.get("exp", 0)),
              RewardList=contents, RewardItemList=item_list(state, item_ids), RewardCharacterList=fighters,
              questPoint=quest_point(state))


@api("quest/reward")
def quest_reward(req):
    q = int(req.get("QuestIndex") or 0)
    state, entries, fields = claim_quests([q])
    row = quest_rows().get(q)
    if entries or row:
        fields["Quest"] = entries[0] if entries else quest_entry(state, row)
    return ok(**fields)


@api("quest/rewardAll")
def quest_reward_all(req):
    state, entries, fields = claim_quests([int(q) for q in req.get("QuestIndexList") or []])
    return ok(QuestList=entries, **fields)


@api("character/characterGradeUp")
def character_grade_up(req):
    def apply(state, c, ch, req):
        c["grade"] = max(int(c.get("grade", 3)) + 1, int(ch.get("Grade", 0) or 0))
        spend_gold(state, req.get("UsedGold"))
        return use_items(state, req.get("ItemList"))
    r = growth_request("characterGradeUp", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(AccountMoney=money(state), ItemList=item_list(state, used),
              Character=simple(c, "CharacterSimple", start_grades()))


@api("character/characterLimitBreak")
def character_limit_break(req):
    def apply(state, c, ch, req):
        c["limitBreakGrade"] = int(req.get("NextLimitBreakGrade", c.get("limitBreakGrade", 0)) or 0)
        c["limitBreakProgress"] = int(req.get("NextLimitBreakProgressCount", c.get("limitBreakProgress", 0)) or 0)
        spend_gold(state, req.get("UsedGold"))
        return use_items(state, (req.get("SoulItemList") or []) + (req.get("LimitBreakItemList") or []))
    r = growth_request("characterLimitBreak", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(Character=simple(c, "CharacterSimple6", start_grades()), ItemList=item_list(state, used),
              AccountMoney=money(state))


@api("character/characterEnchant")
def character_enchant(req):
    def apply(state, c, ch, req):
        for k, f in (("enchantHp", "AddEnchantHp"), ("enchantAtk", "AddEnchantAtk"), ("enchantDef", "AddEnchantDef")):
            c[k] = int(c.get(k, 0)) + int(req.get(f, 0) or 0)
        return use_items(state, req.get("ItemList"))
    r = growth_request("characterEnchant", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(Character=simple(c, "CharacterSimple7", start_grades()), ItemList=item_list(state, used))


# ---------------------------------------------------------------- awakening (tools/gen_growth.py: Awaken* tables)
# save.json fighter "awaken" = Character.Awaken, the phase (0 = not awakened), "awakenExp" = Character.AwakenExp (the
# awakened level comes from AwakenLevelTable). As on the other growth pages the client works out the result and
# sends what it spent; the awakened LEVEL UP and AWAKENED ENHANCEMENT pages reuse the plain pages' replies.
@api("character/awaken")
def character_awaken(req):
    def apply(state, c, ch, req):
        c["awaken"] = max(int(c.get("awaken", 0)) + 1, int(req.get("Phase", 0) or 0))
        spend_gold(state, req.get("UsedGold"))
        return use_items(state, sum((req.get(f"slot{i}ItemList") or [] for i in range(1, 5)), []))
    r = growth_request("characterAwaken", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(AccountMoney=money(state), ItemList=item_list(state, used),
              Character=simple(c, "CharacterSimple6", start_grades()))


@api("character/awakenLevelUp")
def character_awaken_level_up(req):
    def apply(state, c, ch, req):
        c["awakenExp"] = int(c.get("awakenExp", 0)) + int(req.get("AddExp", 0) or 0)
        return use_items(state, req.get("ItemList"))
    r = growth_request("characterAwakenLevelUp", req, apply)
    if isinstance(r, dict):
        return r
    state, c, used = r
    return ok(LevelUpSuccess=1, ItemList=item_list(state, used), Character=simple(c, "CharacterSimple", start_grades()))


@api("character/awakenEnchant")
def character_awaken_enchant(req):
    return character_enchant(req)


# ---------------------------------------------------------------- core board (tools/gen_cores.py: Core* tables)
# A fighter's board is CharacterTable.coreBoardIndex; its unlocked spots (CoreTreeIndexes) are save.json fighter
# "cores", sent with player/profile (CharacterCoreList). save.json "allCores": true counts every spot of every
# fighter's board as unlocked (tools/account.py allcores on|off).
def core_boards():
    """{characterIndex: {CoreTreeIndex: CoreTreeTable row of the fighter's board}} (the tables read once)"""
    by_board = {}
    for r in table_rows("CoreTreeTable"):
        by_board.setdefault(r["coreBoardIndex"], {})[r["coreTreeIndex"]] = r
    return {r["characterIndex"]: by_board.get(r.get("coreBoardIndex", 0), {}) for r in table_rows("CharacterTable")}


def core_trees(index):
    return core_boards().get(index, {})


def unlocked_cores(state, c, boards=None):
    trees = (boards or core_boards()).get(c["index"], {})
    if state.get("allCores"):
        return sorted(trees)
    return sorted(i for i in c.get("cores", []) if i in trees)


def core_reply(state, c, used=None):
    return ok(CharacterIndex=c["index"], AccountMoney=money(state), ItemList=item_list(state, used or []),
              CoreList=unlocked_cores(state, c))


def acquire_cores(req, pick):
    """Unlock the spots pick(fighter, its tree rows, unlocked set) names, spending what the client says it used."""
    log_growth("coreAcquire", req)
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        c = character_state(state, int(req.get("CharacterIndex", 0) or 0))
        trees = core_trees(c["index"])
        have = set(unlocked_cores(state, c))
        c["cores"] = sorted(have | set(pick(c, trees, have)))
        spend_gold(state, req.get("UsedCost"))
        used = use_items(state, req.get("ItemList"))
        save_state(state)
    return core_reply(state, c, used)


@api("core/coreInfo")
def core_info(req):
    state = load_state()
    if state is None:
        return {"ResultCode": 1, "ResultMessage": "no account"}
    c = next((c for c in owned_characters(state) if c["index"] == int(req.get("CharacterIndex", 0) or 0)), None)
    return ok(CharacterIndex=c["index"], CoreList=unlocked_cores(state, c)) if c else ok()


@api("core/coreAcquire")
def core_acquire(req):
    def path(c, trees, have):
        """the spot asked for and every locked one before it (a line's last spot unlocks the whole line)"""
        out, i = [], int(req.get("CoreTreeIndex", 0) or 0)
        while i in trees and i not in have:
            out.append(i)
            i = trees[i].get("preUnlockCoreTreeIndex", 0)
        return out
    return acquire_cores(req, path)


@api("character/battleCardEquipUpdate")
def battle_card_equip_update(req):
    """The fighter's eight card slots (save.json fighter "battleCards"); a card taken from another fighter
    (PrevCharacterIndexN) leaves that fighter's slot."""
    ch = req.get("Character") or {}
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        c = character_state(state, int(ch.get("CharacterIndex", 0) or 0))
        c["battleCards"] = [int(ch.get(f"BattleCardNo{i}", 0) or 0) for i in range(1, 9)]
        others = []
        for i, no in enumerate(c["battleCards"], 1):
            prev = int(ch.get(f"PrevCharacterIndex{i}", 0) or 0)
            if no and prev and prev != c["index"]:
                o = character_state(state, prev)
                o["battleCards"] = [0 if x == no else x for x in o.get("battleCards", [0] * 8)]
                others.append(o)
        save_state(state)
    return ok(Character=simple(c, "CharacterSimple2"), CharacterList=[simple(o, "CharacterSimple8") for o in others])


# ---------------------------------------------------------------- battle cards (tools/gen_cards.py: special cards)
# save.json "allSpecialCards": true owns one of every special (SP) card at its top grade (tools/account.py spcards
# on|off); a card's BattleCardNo is its battleCardIndex.
# A card's SkillIndex is its own BattleCardTable skillIndex, whoever wears it: the client puts it in battle slot 5
# (CharacterData.BattleCard.CreateSkill: SkillIndexes[4]; card slot 6 fills slot 11) and plays that row's move on
# any version of the card's fighter - the practice room builds its cards straight from BattleCardTable
# (Model_TrainingRenew.CreateBattleCard) and Kyo XI played Kyo '94's Ura 121 card there with the '94 row
# ("...Ura121ShikiAmanoMurakumo#1", 2026-11-02).
def card_passives(row):
    """a new set / option card's option skills at level 1: the BattleCardTable row's passiveSkill1-3Index (the card
    screen lists the server's PassiveIndex1-3; a summoned card showed none without them)"""
    return [[row[f"passiveSkill{n}Index"], 1] for n in range(1, int(row.get("passiveCount") or 0) + 1)
            if row.get(f"passiveSkill{n}Index")]


def battle_cards(state):
    """the special cards of "allSpecialCards", then save.json "cards": the account's set / option cards and the
    growth of any card (same "no"; tools/max_build.py, tools/gen_builds.py): {"no", "index", "grade", "exp",
    "skillLevel", "awaken" (transcends done; the screens show ALV = awaken + 1), "awakeBuff" (BattleCardAwakeBuffTable
    index), "awakeBuffLevel", "passives": [[BuffTable index, level], ...] (the option skills)}"""
    made = state.get("created", now_ms())
    rows = {r["battleCardIndex"]: r for r in table_rows("BattleCardTable")}
    out = {}
    if state.get("allSpecialCards"):
        for r in rows.values():
            if r.get("cardType") == 3:
                out[r["battleCardIndex"]] = apidefaults.default(
                    "BattleCard", BattleCardNo=r["battleCardIndex"], BattleCardIndex=r["battleCardIndex"],
                    Grade=r.get("cardEndGrade", 6), SkillIndex=r.get("skillIndex", 0),
                    SkillLevel=1 if r.get("skillIndex") else 0, CreateTime=made, Qty=1)
    for e in state.get("cards", []):
        r = rows.get(e["index"])
        if r is None:
            continue
        passives = e.get("passives") or card_passives(r)
        out[e["no"]] = apidefaults.default(
            "BattleCard", BattleCardNo=e["no"], BattleCardIndex=e["index"], Grade=e.get("grade", r.get("cardEndGrade", 6)),
            Exp=e.get("exp", 0), SkillIndex=r.get("skillIndex", 0), SkillLevel=e.get("skillLevel", 1),
            **{f"PassiveIndex{i}": b for i, (b, _) in enumerate(passives, 1)},
            **{f"PassiveLevel{i}": lv for i, (_, lv) in enumerate(passives, 1)},
            awaken=e.get("awaken", 0), awakeBuffIndex=e.get("awakeBuff", 0), awakeBuffLevel=e.get("awakeBuffLevel", 0),
            CreateTime=e.get("created", made), Qty=1)
    return list(out.values())


def imprint_stones(state):
    """save.json "stones": [{"no", "index" (ImprintStoneTable), "enchant"}] (tools/max_build.py)"""
    made = state.get("created", now_ms())
    return [apidefaults.default("ImprintStoneWEBData", ImprintStoneNo=e["no"], ImprintStoneIndex=e["index"],
                                Enchant=e.get("enchant", 0), CreateTime=e.get("created", made))
            for e in state.get("stones", [])]


@api("character/changeUp")
def change_up(req):
    """Change Up (tools/gen_changeup.py): the fighter's ChangeUpTable kit (one) makes it EX (save.json fighter "ex": 1):
    its ExAwakenStatusTable stats and the EX awakening (A9). An "unlimited" account needs no kit."""
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        index = int(req.get("characterIndex") or req.get("CharacterIndex") or 0)
        row = next((r for r in table_rows("ChangeUpTable") if r["changeUpFighterIndex"] == index), None)
        if row is None:
            return {"ResultCode": 1, "ResultMessage": "no change up for this fighter"}
        c = character_state(state, index)
        if c.get("ex"):
            return {"ResultCode": 1, "ResultMessage": "already EX"}
        kit = str(row["changeUpItemIndex"])
        inv = items(state)
        if not state.get("unlimited"):
            if int(inv.get(kit, 0)) < 1:
                return {"ResultCode": 1, "ResultMessage": "no change up kit"}
            inv[kit] = int(inv[kit]) - 1
        c["ex"] = 1
        save_state(state)
    return ok(Character=simple(c, "CharacterSimple6"), remainItem=item_list(state, [kit])[0])


# ---------------------------------------------------------------- EX core board (tools/gen_excore.py: AwakenCore*)
# save.json fighter "exCores" = {coreIndex: level}. An EX fighter (changed up, or an EX frame) has one EX core point
# per awakened level (real: 50 at Lv 50, 90 = 75 + 14 + 1 at Lv 90); Character.corePoint is what is left, and the
# profile's characterAwakenCoreList the levels. A reset takes ConfigTable 195007 of item 195006 (the client's own
# check, UIPopup_ResetAwakenCoreLevel) unless the account is "unlimited".
EX_FRAME = 100
_ex_cache = {}


def ex_tables():
    """(fighter -> board, board -> {coreIndex: AwakenCoreTable row}, EX-frame fighters, awakened level EXP steps),
    read again when a table file changes"""
    files = [os.path.join(TABLES, t + ".json") for t in ("CharacterTable", "AwakenCoreTable", "AwakenLevelTable")]
    key = tuple(os.path.getmtime(f) if os.path.exists(f) else 0 for f in files)
    if _ex_cache.get("key") != key:
        chars = table_rows("CharacterTable")
        cores = {}
        for r in table_rows("AwakenCoreTable"):
            cores.setdefault(r["awakenCoreBoardIndex"], {})[r["awakenCoreIndex"]] = r
        _ex_cache.update(key=key, data=(
            {r["characterIndex"]: r["awakenCoreBoardIndex"] for r in chars if r.get("awakenCoreBoardIndex")}, cores,
            {r["characterIndex"] for r in chars if r.get("frameGrade") == EX_FRAME},
            sorted(r.get("reqAccumulatedExp1", 0) for r in table_rows("AwakenLevelTable"))))
    return _ex_cache["data"]


def awakened_level(c):
    """the client's awakened level: AwakenLevelTable's EXP steps passed, at most 10 a phase (0 = not awakened)"""
    phase = int(c.get("awaken", 0) or 0)
    if phase <= 0:
        return 0
    exp = int(c.get("awakenExp", 0) or 0)
    return min(1 + sum(1 for need in ex_tables()[3] if need <= exp), 10 * phase)


def ex_core_levels(c):
    return {int(k): int(v) for k, v in (c.get("exCores") or {}).items()}


def ex_core_points(c):
    boards, _, ex_frames, _ = ex_tables()
    if c["index"] not in boards or not (c.get("ex") or c["index"] in ex_frames):
        return 0
    return max(0, awakened_level(c) - sum(ex_core_levels(c).values()))


def ex_core_lists(state):
    boards = ex_tables()[0]
    saved = {c["index"]: c for c in state["characters"]}
    return [{"characterIndex": index, "coreList": [{"coreIndex": k, "coreLevel": v}
                                                   for k, v in sorted(ex_core_levels(saved.get(index, {})).items())]}
            for index in sorted(boards)]


@api("core/awakenCoreLevelUp")
def awaken_core_level_up(req):
    """raise one EX core by addLevel: within its maxLevel, its tier's max (AwakenCoreBoardTable) and the points left"""
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        index = int(req.get("characterIndex") or 0)
        core, add = int(req.get("coreIndex") or 0), int(req.get("addLevel") or 0)
        boards, cores, _, _ = ex_tables()
        board = boards.get(index)
        row = cores.get(board, {}).get(core)
        c = character_state(state, index)
        levels = ex_core_levels(c)
        steps = next((r for r in table_rows("AwakenCoreBoardTable") if r["awakenCoreBoardIndex"] == board), {})
        in_step = sum(v for k, v in levels.items() if cores[board].get(k, {}).get("step") == (row or {}).get("step"))
        if row is None or add <= 0 or levels.get(core, 0) + add > row["maxLevel"] or \
                in_step + add > steps.get(f"step{row['step']}MaxLevel", 0) or ex_core_points(c) < add:
            return {"ResultCode": 1, "ResultMessage": "EX core level up not possible"}
        levels[core] = levels.get(core, 0) + add
        c["exCores"] = {str(k): v for k, v in sorted(levels.items())}
        save_state(state)
    return ok(awakenCore={"coreIndex": core, "coreLevel": levels[core]},
              corePoint={"characterIndex": index, "corePoint": ex_core_points(c)})


# ---------------------------------------------------------------- exchange shops (ShopManageTable / ShopGoodsTable)
# The client lists a shop's goods from its own tables (TableData.ShopGoodsTable.SetTableData); the server only
# answers the purchase counts (shop/shopGoodsQtyList) and takes a purchase (shop/shopGoodsBuy): the price (GoodsType
# 13 Item = shopPriceIndex x shopPriceValue, 1 Gold, 2 rubies) and gives the goods (shopGoodsType 13 Item =
# giveItemIndex x giveItemCount: ShopItemInfo.SetData reads the kind from shopGoodsType). save.json
# "shopBuys" = {goodsIndex: count}. First shop: the Change Up Kit Exchange (tools/gen_changeup.py).
GOODS_ITEM, GOODS_GOLD, GOODS_CASH, GOODS_AP = 13, 1, 2, 3


SHOP_WEEKLY = 4      # ShopBuyAbleResetType.Weekly: the count starts over with the Team Relay week (tr_week)


def shop_goods(index):
    return next((r for r in table_rows("ShopGoodsTable") if r["shopGoodsIndex"] == index), None) or {}


# The Secret Shop (tools/gen_secretshop.py): ShopType 10 has isSellGoodsRandomList 1, so the client lists the goods
# sent in PrivateShopGoodsIndexList (NetworkManagerWEB.Parse_ShopGoodsQtyList). Every refreshHours (4, real) block of
# local time draws stockSize goods; the purchase counts start over with each block. save.json "secretShop" =
# {"slot": block start ms, "goods": [...], "buys": {goodsIndex: count}}.
SECRET_TYPE = 10


def secret_cfg():
    try:
        return json.load(open(os.path.join(TABLES, "secretshop.json"), encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"goods": [], "stockSize": 0, "refreshHours": 4}


def secret_block():
    """(start ms, end ms) of the current refresh block (blocks start at local midnight)"""
    hours = int(secret_cfg().get("refreshHours") or 4)
    tm = time.localtime()
    day = time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday, 0, 0, 0, 0, 0, -1))
    start = day + (tm.tm_hour // hours) * hours * 3600
    return int(start * 1000), int((start + hours * 3600) * 1000)


def secret_shop(state):
    cfg, (start, _end) = secret_cfg(), secret_block()
    s = state.get("secretShop") or {}
    if s.get("slot") != start or any(g not in cfg["goods"] for g in s.get("goods", [])):
        pool = list(cfg["goods"])
        goods = sorted(random.Random(f"{state.get('playerId', '')}-{start}").sample(
            pool, min(int(cfg.get("stockSize") or len(pool)), len(pool))))
        s = state["secretShop"] = {"slot": start, "goods": goods, "buys": {}}
    return s


def shop_bought(state, index):
    """this goods' purchase count: weekly goods count in save.json "shopBuysWeek" = {"week", "counts"}"""
    if shop_goods(index).get("shopType") == SECRET_TYPE:
        return int(secret_shop(state)["buys"].get(str(index), 0))
    if shop_goods(index).get("buyAbleCountAccountResetType") == SHOP_WEEKLY:
        w = state.get("shopBuysWeek") or {}
        return int(w.get("counts", {}).get(str(index), 0)) if w.get("week") == tr_week()[0] else 0
    return int(state.get("shopBuys", {}).get(str(index), 0))


def shop_qty(state, index):
    row = shop_goods(index)
    reset = (secret_block()[1] if row.get("shopType") == SECRET_TYPE else
             tr_week()[2] if row.get("buyAbleCountAccountResetType") == SHOP_WEEKLY else 0)
    return {"GoodsIndex": index, "BuyType": 0, "BuyCount": shop_bought(state, index),
            "UpdateTime": now_ms(), "ResetTime": reset, "customPackageInstantChoice": []}


@api("shop/shopGoodsQtyList")
def shop_goods_qty_list(req):
    state = load_state()
    if state is None:
        return {"ResultCode": 1, "ResultMessage": "no account"}
    kind = int(req.get("ShopType") or 0)
    if kind == SECRET_TYPE:
        s = secret_shop(state)
        save_state(state)
        start, end = secret_block()
        return ok(ServerUtcTime=now_ms(), PrivateShopGoodsIndexList=s["goods"],
                  ShopRefreshInfo={"ManualRefreshCount": 0, "RefreshCount": 0, "RefreshTime": start,
                                   "FreeRefreshCount": 0, "nextRefreshTime": end},
                  ShopGoodsQtyList=[shop_qty(state, g) for g in s["goods"]])
    bought = state.get("shopBuys", {})
    return ok(ServerUtcTime=now_ms(), ShopGoodsQtyList=[
        shop_qty(state, r["shopGoodsIndex"]) for r in table_rows("ShopGoodsTable")
        if r.get("shopType") == kind and (str(r["shopGoodsIndex"]) in bought
                                          or r.get("buyAbleCountAccountResetType") == SHOP_WEEKLY)])


@api("shop/shopGoodsBuy")
def shop_goods_buy(req):
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        index, count = int(req.get("GoodsIndex") or 0), max(1, int(req.get("BuyCount") or 1))
        row = next((r for r in table_rows("ShopGoodsTable") if r["shopGoodsIndex"] == index), None)
        if row is None:
            return {"ResultCode": 1, "ResultMessage": "no such goods"}
        if row.get("shopType") == SECRET_TYPE and index not in secret_shop(state)["goods"]:
            return {"ResultCode": 1, "ResultMessage": "not in stock"}
        limit = int(row.get("buyAbleCountAccount") or 0)
        if limit and shop_bought(state, index) + count > limit:
            return {"ResultCode": 1, "ResultMessage": "purchase limit reached"}
        inv = items(state)
        price, cost = row.get("shopPriceType"), int(row.get("shopPriceValue", 0)) * count
        paid = str(row.get("shopPriceIndex", 0))
        if not state.get("unlimited"):
            if price == GOODS_ITEM:
                if int(inv.get(paid, 0)) < cost:
                    return {"ResultCode": 1, "ResultMessage": "not enough items"}
                inv[paid] = int(inv[paid]) - cost
            elif price in (GOODS_GOLD, GOODS_CASH):
                key = "Gold" if price == GOODS_GOLD else "Cash"
                wallet = regen_ap(state)
                if wallet.get(key, 0) < cost:
                    return {"ResultCode": 1, "ResultMessage": "not enough money"}
                wallet[key] -= cost
        given, n = str(row.get("giveItemIndex", 0)), int(row.get("giveItemCount", 1)) * count
        if row.get("shopGoodsType") == GOODS_ITEM:
            inv[given] = int(inv.get(given, 0)) + n
        elif row.get("shopGoodsType") == GOODS_AP:
            wallet = regen_ap(state)
            wallet["ActivePoint"] = int(wallet.get("ActivePoint", 0)) + n
        if row.get("shopType") == SECRET_TYPE:
            sb = secret_shop(state)["buys"]
            sb[str(index)] = int(sb.get(str(index), 0)) + count
            d = daily(state)
            d["secretShop"] = int(d.get("secretShop", 0)) + 1
        elif row.get("buyAbleCountAccountResetType") == SHOP_WEEKLY:
            week = tr_week()[0]
            w = state.get("shopBuysWeek") or {}
            if w.get("week") != week:
                w = state["shopBuysWeek"] = {"week": week, "counts": {}}
            w["counts"][str(index)] = int(w["counts"].get(str(index), 0)) + count
        else:
            buys = state.setdefault("shopBuys", {})
            buys[str(index)] = int(buys.get(str(index), 0)) + count
        save_state(state)
    # the client adds RewardItemList to its inventory (NetworkManagerWEB.TakeAndAddItemList -> InnerAddCount): the
    # amount given, not the new total; RemainItem sets the price item's count (ItemInventory.InnerSet)
    return ok(ShopGoodsQty=shop_qty(state, index), AccountMoney=money(state),
              RewardItemList=[{"ItemIndex": int(given), "Qty": n, "Lock": 0, "UpdateTime": now_ms()}]
              if row.get("shopGoodsType") == GOODS_ITEM else [],
              RemainItem=item_list(state, [paid])[0] if price == GOODS_ITEM else None)


# ---------------------------------------------------------------- summon (tools/gen_gacha.py)
# gacha2/gachaInfo opens every GachaMainTable banner (OperateSchedule Category 20, Index = gachaMainIndex;
# NetworkManagerWEB.TakeGachaTypeDataList) and returns the picks (gachaSelectPickUpList: selectPickUpList = lineup
# rows, comma list), the purchase counts (GachaDefaultList, per banner and normalCategory - the Reset Summon's
# "Remaining 1/1") and the pity counts (GachaMileageList: Mileage = pulls, RewardList = the milestones taken);
# gacha2/selectPickUp keeps the picks (save.json "gachaPicks", by unit: pick_rows). gacha2/gachaDefaultPlay pays the
# button's price (the
# GachaNormalGroupTable row of the banner's gachaGroup with the request's normalCategory: rubies, gold, friendship
# points or an item - Kaya's diamonds) and draws goodsCount lineup rows by their View Rate rates (lineup_rates: a pick
# at the pick-up row's selectPickupFixedRate), at least flagCount rows of flagRarilty stars or more; pays the button's
# bonus (GachaRewardBonusGroupTable: diamonds, RewardBonusContentsList) and counts the pulls for the banner's pity. A
# fighter the account has pays its memory instead (the guides: duplicates pay memories; CharacterReward
# fighterMemoryIndex / Qty, ours 1), a new one joins at the row's grade; cards join save.json "cards" (numbers from
# GACHA_CARD_NO up). The Reset Summon (gachaType 101; seen in game): the first summon (GachaReset 1, Item.Qty = the
# price) is paid; the result's "Retry" sends GachaReset 1 with Item.Qty 0 and summons for free, taking back what the
# last one gave (save.json "gachaReset"); "Keep" asks for confirmation and sends GachaReset 0, which ends it with the
# last result kept; exactly one 5-star a summon (the guides).
# gacha2/gachaMileageReward pays a reached pity step once: its RewardGroupTable group, or at the last step the
# MileageGoodsGroupTable row picked (MileageGoodsGroupIndex), after which the banner's pity starts over. Seen in game:
# right after a summon the client claims the last step by itself with no pick (MileageGoodsGroupIndex 0); the real
# game then kept a Special Loyalty Reward to choose later (the guides: "stored in the special loyalty reward banner
# and they do not expire"): the reply's mileageSelectReward true (GachaModel.RecvGachaMileageReward opens the
# notice), gachaInfo's gachaMileageSelectList the kept rewards with their choices (MileageManager.
# ParseMileageReward; the strip shows that page when ConfigTable 80008 is set, GachaFilter.CacheDummySort), and
# gacha2/gachaMileageSelectReward {gachaTypeIndex, seq, contentsIndex} gives the one chosen (save.json
# "gachaLoyalty"). The choices are the banner's rate-up picks at the time (the guides: "choose any of your rated-up
# units"), or its featured units when none was picked.
GACHA_CATEGORY = 20                    # OperateSchedule.Category of the summon banners
MEMORY_ITEM_BASE = 300000              # a fighter's memory = item 300000 + fighter (tools/gen_growth.py)
GACHA_CARD_NO, DUPLICATE_MEMORY = 70_000_000, 1
RESET_GACHA, FIGHTER_GOODS, CARD_GOODS = 101, 11, 12


def gacha_banners():
    return {r["gachaMainIndex"]: r for r in table_rows("GachaMainTable")}


def lineup_rows(banner):
    """the banner's lineup: the GachaNormalGoodsGroupTable rows of its normalGoodsGroup list"""
    groups = {int(g) for g in str(banner.get("normalGoodsGroup") or "").split(",") if g.strip().isdigit()}
    return [r for r in table_rows("GachaNormalGoodsGroupTable") if r["gachaNormalGoodsGroup"] in groups]


def pick_rows(state, banner):
    """the banner's picked lineup rows. save.json "gachaPicks" keeps a pick as its unit [rewardType, contentsIndex],
    not its row: tools/gen_gacha.py numbers a pick-up lineup in ranking order, which moves as the roster grows"""
    rows = {(r["rewardType"], r["contentsIndex"]): r for r in lineup_rows(banner)}
    return [rows[tuple(p)] for p in state.get("gachaPicks", {}).get(str(banner["gachaMainIndex"]), [])
            if isinstance(p, list) and tuple(p) in rows]


def gacha_picks(state):
    """every banner the player set picks on, a cleared one with an empty list (SelectPickupManager.Parse takes "")"""
    banners = gacha_banners()
    return [{"gachaTypeIndex": int(b), "forcePickUp": 0, "selectPickUpList": ",".join(
                str(r["gachaNormalGoodsGroupIndex"]) for r in pick_rows(state, banners[int(b)]))}
            for b in sorted(state.get("gachaPicks", {})) if int(b) in banners]


def gacha_buys(state):
    """GachaDefaultList: purchase counts by "banner:normalCategory" (save.json "gachaBuys")"""
    out = []
    for key, n in sorted(state.get("gachaBuys", {}).items()):
        if ":" in key:
            banner, category = key.split(":")
            out.append(apidefaults.default("Gacha", GachaTypeIndex=int(banner), GachaDefaultIndex=int(category),
                                           GachaBuyCount=int(n)))
    return out


def gacha_mileage(state, banner):
    m = state.setdefault("gachaMileage", {}).setdefault(str(banner), {"count": 0, "received": []})
    return apidefaults.default("GachaMileage", GachaTypeIndex=int(banner), Mileage=m["count"],
                               RewardList=",".join(str(x) for x in m["received"]))


def gacha_loyalty(state):
    """gachaMileageSelectList: the kept Special Loyalty Rewards and their choices"""
    return [apidefaults.default("GachaMileageSelect", gachaTypeIndex=e["banner"], seq=e["seq"],
                                directionType=e["direction"], createTime=e["created"],
                                rewardGoodsList=[apidefaults.default("RewardGoods", rewardType=t, contentsIndex=i,
                                                                     contentsGrade=g) for t, i, g in e["choices"]])
            for e in state.get("gachaLoyalty", [])]


def loyalty_choices(state, banner):
    """the banner's rate-up picks, else its featured units (MileageGoodsGroupTable): [(GoodsType, index, grade)]"""
    picks = pick_rows(state, banner)
    if picks:
        return [(r["rewardType"], r["contentsIndex"], max(5, r.get("contentsGrade", 5))) for r in picks]
    return [(r["mileageGoodsType"], r["mileageGoodsIndex"], 5) for r in table_rows("MileageGoodsGroupTable")
            if r["mileageGoodsGroup"] == banner.get("mileageGoodsGroup")]


@api("gacha2/gachaInfo")
def gacha_info(req):
    state = load_state() or {}
    banners = gacha_banners()
    schedules = [apidefaults.default("OperateSchedule", Version=1, Category=GACHA_CATEGORY, Index=i,
                                     Detail=apidefaults.default("OperateScheduleData", SubGroup=[i], StartTs=0,
                                                                EndTs=NO_END, OffOnSched=ALWAYS_OPEN))
                 for i in sorted(banners)]
    return ok(GachaScheduleList=schedules, gachaSelectPickUpList=gacha_picks(state), GachaDefaultList=gacha_buys(state),
              GachaMileageList=[gacha_mileage(state, i) for i, b in sorted(banners.items()) if b.get("mileageGroup")],
              gachaMileageSelectList=gacha_loyalty(state))


@api("gacha2/selectPickUp")
def gacha_select_pick_up(req):
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        banner = gacha_banners().get(int(req.get("gachaTypeIndex") or 0))
        if banner is None:
            return {"ResultCode": 1, "ResultMessage": "no such summon"}
        rows = {r["gachaNormalGoodsGroupIndex"]: r for r in lineup_rows(banner)}
        picks = [rows[int(p)] for p in (req.get("selectPickUpIndexList") or []) if int(p) in rows]
        state.setdefault("gachaPicks", {})[str(banner["gachaMainIndex"])] = [[r["rewardType"], r["contentsIndex"]]
                                                                             for r in picks]
        save_state(state)
    return ok(gachaSelectPickUpList=gacha_picks(state))


@api("gacha2/selectPickUpRanking")
def gacha_pick_up_ranking(req):
    """PICK UP RANKING: the banner's ranking (tools/gen_gacha.py pickup_ranking.json: [row index, score], best first);
    the popup shows each score / totalCount (UIPopup_PickupStat.Parse)"""
    try:
        ranking = json.load(open(os.path.join(TABLES, "pickup_ranking.json"), encoding="utf-8"))
    except FileNotFoundError:
        ranking = {}
    rows = ranking.get(str(int(req.get("gachaTypeIndex") or 0)), [])
    return ok(totalCount=float(sum(s for _, s in rows)),
              pickUpRankingList=[{"goodsGroupIndex": i, "score": float(s)} for i, s in rows])


GOODS_RATE_SCALE = 10_000              # goodsProbability per 1 % (tools/gen_gacha.py RATE_SCALE)


def goods_rate(row):
    """a lineup row's rate in %: a rate-up unit's fixedrate, else its goodsProbability (View Rate spreads each grade's
    share over these, and gen_gacha writes the shares as their sums, so the roll matches the popup)"""
    return float(row.get("fixedrate") or 0) or row.get("goodsProbability", 0) / GOODS_RATE_SCALE


FRAME_GRADES = (90, 100, 110)          # purple, red, UE: View Rate splits a 5 / 6-star grade by these frames


def lineup_rates(banner, lineup, picked=(), pick_rate=0.0):
    """{row: rate %} as View Rate shows it (Model_LineUp.InCalcGetGoodsRateInfo): a rate-up row at its fixedrate and a
    pick at the pick-up rate (the guides: "rated-up fighters will get a 0.3% chance to drop"), the other rows sharing
    what is left of their group - the grade, a 5 / 6-star one split by frame when the banner has frameGradeRate - by
    goodsProbability; so a pick takes its rate from its own group (seen in game: the group's share stays)"""
    frames = {}
    if banner.get("frameGradeRate"):
        frames = {(FIGHTER_GOODS, r["characterIndex"]): r.get("frameGrade") for r in player_character_rows()}
        frames.update({(CARD_GOODS, r["battleCardIndex"]): r.get("frameGrade") for r in table_rows("BattleCardTable")})
    groups = {}
    for r in lineup:
        grade, frame = r.get("contentsGrade", 0), frames.get((r["rewardType"], r["contentsIndex"]))
        groups.setdefault((grade, frame if grade >= 5 and frame in FRAME_GRADES else 0), []).append(r)
    rates = {}
    for rows in groups.values():
        share = sum(goods_rate(r) for r in rows)
        fixed = {r["gachaNormalGoodsGroupIndex"]: pick_rate if r["gachaNormalGoodsGroupIndex"] in picked
                 else float(r["fixedrate"]) for r in rows if r["gachaNormalGoodsGroupIndex"] in picked or r.get("fixedrate")}
        rest = [r for r in rows if r["gachaNormalGoodsGroupIndex"] not in fixed]
        left, weight = max(0.0, share - sum(fixed.values())), sum(r.get("goodsProbability", 0) for r in rest)
        rates.update(fixed)
        rates.update({r["gachaNormalGoodsGroupIndex"]: left * r.get("goodsProbability", 0) / weight if weight else 0.0
                      for r in rest})
    return rates


def gacha_draw(lineup, count, flag, rates, one_top=False):
    """count rows by rate (%; lineup_rates), at least flag[1] of flag[0] stars or more; one_top: exactly one row of
    flag[0] stars or more (the Reset Summon)"""
    weights = [rates[r["gachaNormalGoodsGroupIndex"]] for r in lineup]
    rare, need = flag
    top = [(r, w) for r, w in zip(lineup, weights) if r.get("contentsGrade", 0) >= rare]
    if one_top and top:
        low = [(r, w) for r, w in zip(lineup, weights) if r.get("contentsGrade", 0) < rare]
        out = random.choices([r for r, _ in low], weights=[w for _, w in low], k=count - 1)
        return out + random.choices([r for r, _ in top], weights=[w for _, w in top])
    out = random.choices(lineup, weights=weights, k=count)
    if need and sum(1 for r in out if r.get("contentsGrade", 0) >= rare) < need and top:
        out[-1] = random.choices([r for r, _ in top], weights=[w for _, w in top])[0]
    return out


def gacha_card(state, index):
    rows = {r["battleCardIndex"]: r for r in table_rows("BattleCardTable")}
    r = rows.get(index, {})
    cards = state.setdefault("cards", [])
    no = max([GACHA_CARD_NO] + [c["no"] for c in cards]) + 1
    entry = {"no": no, "index": index, "grade": r.get("cardStartGrade", 5), "exp": 0, "skillLevel": 1,
             "created": now_ms(), "passives": card_passives(r)}
    cards.append(entry)
    return apidefaults.default("BattleCard", BattleCardNo=no, BattleCardIndex=index, Grade=entry["grade"],
                               SkillIndex=r.get("skillIndex", 0), SkillLevel=1 if r.get("skillIndex") else 0,
                               CreateTime=entry["created"], Qty=1,
                               **{f"PassiveIndex{i}": b for i, (b, _) in enumerate(entry["passives"], 1)},
                               **{f"PassiveLevel{i}": lv for i, (_, lv) in enumerate(entry["passives"], 1)})


def gacha_give(state, kind, index, grade, given):
    """one unit of a summon -> (CharacterReward or None, BattleCard or None); `given` records what was added
    (the Reset Summon takes it back on a reroll)"""
    inv = items(state)
    if kind == CARD_GOODS:
        card = gacha_card(state, index)
        given.append(["card", card["BattleCardNo"]])
        return None, card
    if kind == ITEM_GOODS:
        inv[str(index)] = int(inv.get(str(index), 0)) + 1
        given.append(["item", index, 1])
        return None, None
    if owns(state, index):
        memory = MEMORY_ITEM_BASE + index
        inv[str(memory)] = int(inv.get(str(memory), 0)) + DUPLICATE_MEMORY
        given.append(["item", memory, DUPLICATE_MEMORY])
        return apidefaults.default("CharacterReward", CharacterIndex=index, Grade=grade, fighterMemoryIndex=memory,
                                   fighterMemoryIndexQty=DUPLICATE_MEMORY), None
    given.append(["fighter", index])
    return give_fighter(state, index, grade), None


def gacha_take_back(state, given):
    """undo gacha_give (a Reset Summon reroll)"""
    inv = items(state)
    for g in given:
        if g[0] == "card":
            state["cards"] = [c for c in state.get("cards", []) if c["no"] != g[1]]
        elif g[0] == "item":
            inv[str(g[1])] = max(0, int(inv.get(str(g[1]), 0)) - g[2])
        elif g[0] == "fighter":
            state["characters"] = [c for c in state.get("characters", []) if c["index"] != g[1]]


def gacha_bonus(state, button):
    """the button's GachaRewardBonusGroupTable rows (Kaya's diamonds) -> RewardBonusContentsList"""
    out, inv = [], items(state)
    for r in table_rows("GachaRewardBonusGroupTable"):
        if button.get("bonusReward") and r["gachaRewardBonusGroup"] == button["bonusReward"]:
            n, index = int(r.get("itemCountValue", 0)), int(r.get("rewardItemIndex", 0))
            inv[str(index)] = int(inv.get(str(index), 0)) + n
            out.append(apidefaults.default("RewardContents", GoodsType=ITEM_GOODS, Count=n, ContentsIndex=index,
                                           ContentsCount=n, ContentsType=ITEM_GOODS))
    return out


@api("gacha2/gachaDefaultPlay")
def gacha_default_play(req):
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        banner = gacha_banners().get(int(req.get("GachaTypeIndex") or 0))
        category = int(req.get("normalCategory") or 0)
        button = next((r for r in table_rows("GachaNormalGroupTable") if banner and
                       r["gachaNormalGroup"] == banner["gachaGroup"] and r.get("normalCategory") == category), None)
        if button is None:
            return {"ResultCode": 1, "ResultMessage": "no such summon"}
        index = banner["gachaMainIndex"]
        reset = banner.get("gachaType") == RESET_GACHA
        pending = state.setdefault("gachaReset", {}).get(str(index)) if reset else None
        rolled = isinstance(pending, list)               # a result shown and not kept yet
        if reset and rolled and int(req.get("GachaReset") or 0) == 0:
            # "Keep" (seen: GachaReset 0 after the confirmation): the last result stays, no more rerolls
            state["gachaReset"][str(index)] = "kept"
            save_state(state)
            return ok(GachaDefault=apidefaults.default("Gacha", GachaTypeIndex=index, GachaDefaultIndex=category,
                                                       GachaBuyCount=int(state.get("gachaBuys", {}).get(
                                                           f"{index}:{category}", 0))),
                      AccountMoney=money(state), GachaReset=0)
        if reset and pending == "kept":
            return {"ResultCode": 1, "ResultMessage": "reset summon already kept"}
        free = reset and rolled                          # a Reset Summon reroll ("Retry": GachaReset 1, no price)
        cost, inv = int(button.get("priceValue", 0)), items(state)
        key = {RUBY_GOODS: "Cash", GOLD_GOODS: "Gold", FRIEND_POINT_GOODS: "FriendPoint"}.get(button.get("priceType"))
        wallet = regen_ap(state)
        if not free and not state.get("unlimited"):
            if key:
                if int(wallet.get(key, 0)) < cost:
                    return {"ResultCode": 1, "ResultMessage": "not enough money"}
                wallet[key] = int(wallet.get(key, 0)) - cost
            elif button.get("priceType") == ITEM_GOODS:
                paid = str(button.get("priceIndex", 0))
                if int(inv.get(paid, 0)) < cost:
                    return {"ResultCode": 1, "ResultMessage": "not enough items"}
                inv[paid] = int(inv[paid]) - cost
        if free:
            gacha_take_back(state, pending)
        lineup = lineup_rows(banner)
        pick_rate = next((float(r.get("selectPickupFixedRate") or 0) for r in table_rows("GachaSelectPickUpTable")
                          if r["gachaSelectPickUpIndex"] == banner.get("selectPickup")), 0.0)
        rates = lineup_rates(banner, lineup, {r["gachaNormalGoodsGroupIndex"] for r in pick_rows(state, banner)},
                             pick_rate)
        fighters, cards, gained, given = [], [], {}, []
        count = int(button.get("goodsCount", 1))
        for r in gacha_draw(lineup, count, (button.get("flagRarilty", 0), button.get("flagCount", 0)), rates,
                            one_top=reset):
            kind = r.get("rewardType")
            fighter, card = gacha_give(state, kind, r["contentsIndex"], r.get("contentsGrade", 3), given)
            if fighter:
                fighters.append(fighter)
            if card:
                cards.append(card)
            if kind == ITEM_GOODS:
                gained[r["contentsIndex"]] = gained.get(r["contentsIndex"], 0) + 1
        if reset:
            state["gachaReset"][str(index)] = given
        bonus_list = [] if free else gacha_bonus(state, button)
        buys = state.setdefault("gachaBuys", {})
        if not free:
            buys[f"{index}:{category}"] = int(buys.get(f"{index}:{category}", 0)) + 1
        mileage = 0
        if banner.get("mileageGroup") and not free:
            m = state.setdefault("gachaMileage", {}).setdefault(str(index), {"count": 0, "received": []})
            m["count"] += count
            mileage = m["count"]
        save_state(state)
    return ok(GachaDefault=apidefaults.default("Gacha", GachaTypeIndex=index, GachaDefaultIndex=category,
                                               GachaBuyCount=int(buys.get(f"{index}:{category}", 0))),
              AccountMoney=money(state), RewardCharacterList=fighters, RewardBattleCardList=cards,
              RewardItemList=[{"ItemIndex": i, "Qty": n, "Lock": 0, "UpdateTime": now_ms()} for i, n in gained.items()],
              RewardBonusContentsList=bonus_list, Mileage=mileage, GachaReset=int(reset))


@api("gacha2/gachaMileageReward")
def gacha_mileage_reward(req):
    """a pity step once: its reward group, or at the last step the picked unit; then the pity starts over"""
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        index = int(req.get("GachaTypeIndex") or 0)
        banner = gacha_banners().get(index)
        if not banner or not banner.get("mileageGroup"):
            return {"ResultCode": 1, "ResultMessage": "no pity"}
        group = int(str(banner["mileageGroup"]).split(",")[0])
        steps = sorted((r for r in table_rows("GachaMileageGroupTable") if r["mileageGroup"] == group),
                       key=lambda r: r["mileageCount"])
        m = state.setdefault("gachaMileage", {}).setdefault(str(index), {"count": 0, "received": []})
        want = int(req.get("RewardMileage") or 0)
        step = next((r for r in steps if r["mileageCount"] == want), None) or next(
            (r for r in steps if r["mileageCount"] <= m["count"] and r["mileageCount"] not in m["received"]), None)
        if step is None or step["mileageCount"] > m["count"] or step["mileageCount"] in m["received"]:
            return {"ResultCode": 1, "ResultMessage": "pity step not reached"}
        fighters, cards, contents, item_ids, given, kept = [], [], [], [], [], False
        if step.get("useMileageSelectReward"):
            pick = int(req.get("MileageGoodsGroupIndex") or 0)
            row = next((r for r in table_rows("MileageGoodsGroupTable") if r["mileageGoodsGroupIndex"] == pick and
                        r["mileageGoodsGroup"] == banner.get("mileageGoodsGroup")), None)
            if row is not None:
                fighter, card = gacha_give(state, row["mileageGoodsType"], row["mileageGoodsIndex"], 6, given)
                fighters += [fighter] if fighter else []
                cards += [card] if card else []
            else:                            # kept as a Special Loyalty Reward, chosen later
                loyalty = state.setdefault("gachaLoyalty", [])
                loyalty.append({"banner": index, "seq": max([0] + [e["seq"] for e in loyalty]) + 1,
                                "direction": banner.get("directionType", 1), "created": now_ms(),
                                "choices": loyalty_choices(state, banner)})
                kept = True
        else:
            contents, item_ids, more = give_rewards(state, step["mileageReward"])
            fighters += more
        m["received"].append(step["mileageCount"])
        if len(m["received"]) >= len(steps):
            m["count"], m["received"] = max(0, m["count"] - steps[-1]["mileageCount"]), []
        save_state(state)
    return ok(AccountMoney=money(state), RewardCharacterList=fighters, RewardBattleCardList=cards,
              RewardItemList=item_list(state, [str(i) for i in item_ids]) if item_ids else [],
              GachaMileage=gacha_mileage(state, index), RewardList=contents, mileageSelectReward=kept)


@api("gacha2/gachaMileageSelectReward")
def gacha_mileage_select_reward(req):
    """a kept Special Loyalty Reward: the unit chosen (contentsIndex) among its choices"""
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        banner, seq = int(req.get("gachaTypeIndex") or 0), int(req.get("seq") or 0)
        loyalty = state.setdefault("gachaLoyalty", [])
        entry = next((e for e in loyalty if e["seq"] == seq and e["banner"] == banner), None) or \
            next((e for e in loyalty if e["seq"] == seq), None)
        if entry is None:
            return {"ResultCode": 1, "ResultMessage": "no such reward"}
        want = int(req.get("contentsIndex") or 0)
        choice = next((c for c in entry["choices"] if c[1] == want), None)
        if choice is None:
            return {"ResultCode": 1, "ResultMessage": "not one of the choices"}
        fighter, card = gacha_give(state, choice[0], choice[1], choice[2], [])
        loyalty.remove(entry)
        save_state(state)
    return ok(AccountMoney=money(state), RewardCharacterList=[fighter] if fighter else [],
              RewardBattleCardList=[card] if card else [], RewardItemList=[], PostSendFlag=False,
              gachaMileageSelectList=gacha_loyalty(state))


@api("core/awakenCoreReset")
def awaken_core_reset(req):
    """every EX core of the fighter back to 0, its points returned, for the reset item"""
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        index = int(req.get("characterIndex") or 0)
        c = character_state(state, index)
        item, cost = str(int(config_number(195006, 1))), int(config_number(195007, 100))
        inv = items(state)
        if c.get("exCores"):
            if not state.get("unlimited"):
                if int(inv.get(item, 0)) < cost:
                    return {"ResultCode": 1, "ResultMessage": "no EX core reset item"}
                inv[item] = int(inv[item]) - cost
            c["exCores"] = {}
            save_state(state)
    return ok(accountMoney=money(state), corePoint={"characterIndex": index, "corePoint": ex_core_points(c)},
              remainItem=item_list(state, [item])[0])


@api("character/imprintEquip")
def imprint_equip(req):
    """the fighter's five stone slots (save.json fighter "stones"); a stone moved from another fighter leaves its slot"""
    ch = req.get("Character") or {}
    with _lock:
        state = load_state()
        if state is None:
            return {"ResultCode": 1, "ResultMessage": "no account"}
        c = character_state(state, int(ch.get("CharacterIndex", 0) or 0))
        c["stones"] = [int(ch.get(f"ImprintStoneNo{i}", 0) or 0) for i in range(1, 6)]
        for o in state["characters"]:
            if o is not c and o.get("stones"):
                o["stones"] = [0 if no and no in c["stones"] else no for no in o["stones"]]
        save_state(state)
    return ok(Character=apidefaults.default("ImprintStoneEquipWEBData", CharacterIndex=c["index"],
                                            **{f"ImprintStoneNo{i}": no for i, no in enumerate(c["stones"], 1)}))


def card_inventory(cards):
    return apidefaults.default("BattleCardInvenSize", Qty=len(cards), MaxSize=max(200, len(cards) + 50))


# ---------------------------------------------------------------- guild (tools/gen_guild.py; recon/guild_research.md)
# Offline a guild is the player's own (save.json "guild"): guild/create founds it, the player is its master
# (GuildMemberType 203) and only member. The client counts the player as in a guild when the GuildInfo it holds has a
# GuildNo (GuildManager.get_HasGuild), set by guild/create, guild/guildInfo and player/lobby (MyGuildInfo).
# Gold donations fill the guild's fund (OperationAmount), which pays for guild buffs (GuildBuffTable needActiveCost,
# 11 hours each), and give guild EXP and the member's contribution at ConfigTable 20043 / 20044 per gold - the rates
# the donation popup shows (tools/gen_guild.py CONFIG). The lobby's "Guild Fund" box is this week's donations
# (GuildInfo.TotalDonation; its tooltip adds LastWeekDonation), the coin next to the guild's level the fund.
GUILD_NO, GUILD_MASTER = 1, 203


def config_number(key, default=0.0):
    return next((float(r.get("value1") or 0) for r in table_rows("ConfigTable") if r["configIndex"] == key), default)


def guild_level(exp):
    """the client's rule (as for ranks): the first level whose expAccumulate is above the guild's EXP"""
    rows = sorted(table_rows("GuildLevelingTable"), key=lambda r: r["guildLevel"])
    best = next((r for r in rows if r["expAccumulate"] > exp), rows[-1] if rows else {})
    return best.get("guildLevel", 1), best


def guild_info(state, g):
    level, row = guild_level(g.get("exp", 0))
    return apidefaults.default(
        "GuildInfo", GuildNo=g["no"], GuildName=g["name"], MasterUsn=USN, MasterNickName=state["nickname"],
        JoinType=g.get("joinType", 0), JoinLevelLimit=g.get("joinLevelLimit", 0), MemberCount=1,
        MaxMemberCount=row.get("guildMemberCount", 50), GuildExp=g.get("exp", 0), HistoryCount=len(g.get("history", [])),
        OpenFlag=g.get("open", True), BestLevel=level, DonationLimit=donation_limit(g),
        DonationAmount=g.get("fund", 0), OperationAmount=g.get("fund", 0), TotalDonation=guild_week(g)["donated"],
        LastWeekDonation=guild_week(g)["last"])


def donation_limit(g):
    """a member's daily gold donation: the master's setting, else ConfigTable 20042 (the create popup sends 0, and
    the client counts a member at 0 as done for the day)"""
    return g.get("donationLimit") or int(config_number(20042, 25000))


def guild_today(g):
    """today's guild record: gold donated, check-in"""
    d = g.get("today")
    if not d or d.get("day") != soul_day():
        d = g["today"] = {"day": soul_day(), "donated": 0, "checkedIn": False}
    return d


def guild_week(g):
    """this week's and last week's gold donations; weeks as the raid seasons"""
    season, start, _ = raid_season()
    w = g.get("week")
    if not w or w.get("season") != season:
        last = w["donated"] if w and w.get("season") == season - 1 else 0
        w = g["week"] = {"season": season, "donated": g.get("donated", 0) if not w and g.get("created", 0) >= start
                         else 0, "last": last}
    return w


def guild_member(state, g):
    lead = state["characters"][0] if state.get("characters") else {}
    return apidefaults.default(
        "MemberInfo", GuildNo=g["no"], Usn=USN, GameDb=1, NickName=state["nickname"],
        AccountLevel=account_level(state.get("exp", 0)), CharacterIndex=lead.get("index", 0),
        Grade=lead.get("grade", 3), Exp=lead.get("exp", 0), LastLoginTime=now_ms(), JoinStatus=1,
        GuildMemberLevel=GUILD_MASTER, RegTime=g["created"], AccountId="offline", Pid=PLAYER_ID, MsgGuildChat=1,
        DonationAmount=guild_today(g)["donated"], Donation=g.get("contribution", 0), totalDonation=g.get("donated", 0))


def my_guild(state, g):
    today = guild_today(g)
    return apidefaults.default("MyGuildInfo", GuildNo=g["no"], GuildName=g["name"], GuildExp=g.get("exp", 0),
                               DonationAmount=today["donated"], Donation=g.get("contribution", 0),
                               AttendanceReward=today["checkedIn"])


def guild_buffs(g):
    now = now_ms()
    return [{"GuildBuffIndex": int(k), "ExpireTime": t} for k, t in g.get("buffs", {}).items() if t > now]


def guild_level_info(g, before):
    after = guild_level(g.get("exp", 0))[0]
    return {"GuildExp": g.get("exp", 0), "LevelUpDown": 1 if after > before else 0, "RankPoint": 0}


def with_guild(fn):
    """run fn(state, guild) on the saved account's guild and save; {} without one"""
    with _lock:
        state = load_state()
        g = (state or {}).get("guild")
        if not g:
            return {}
        out = fn(state, g)
        save_state(state)
        return out


@api("guild/create")
def guild_create(req):
    with _lock:
        state = load_state()
        if state is None:
            return {}
        row = (table_rows("GuildTable") or [{}])[0]
        if row.get("makePriceType") == 1:
            spend_gold(state, row.get("makePriceValue", 0))
        g = state["guild"] = {"no": GUILD_NO, "name": (req.get("GuildName") or "Guild").strip(),
                              "joinType": int(req.get("JoinType") or 0), "open": bool(req.get("Open", True)),
                              "joinLevelLimit": int(req.get("JoinLevelLimit") or 0),
                              "donationLimit": int(req.get("DonationLimit") or 0), "created": now_ms(), "exp": 0,
                              "fund": 0, "donated": 0, "buffs": {}}
        save_state(state)
    return ok(GuildInfo=guild_info(state, g), MemberInfo=[guild_member(state, g)], AccountMoney=money(state))


@api("guild/guildInfo")
def guild_info_api(req):
    return with_guild(lambda state, g: ok(
        GuildInfo=guild_info(state, g), MemberInfo=[guild_member(state, g)], GuildBuffList=guild_buffs(g),
        MyGuildInfo=my_guild(state, g), GuildDungeonSeasonList=raid_season_list(), GuildCoopSeasonList=[coop_season_info()],
        AttendanceInfo={"TodayAttendanceMemberCount": int(guild_today(g)["checkedIn"]), "AttendanceMemberCount": 1}))


@api("guild/memberList")
def guild_member_list(req):
    return with_guild(lambda state, g: ok(List=[guild_member(state, g)], GuildLevelInfo=guild_level_info(g, 0)))


@api("guild/buffList")
def guild_buff_list(req):
    return with_guild(lambda state, g: ok(GuildBuffList=guild_buffs(g)))


@api("guild/buffOn")
def guild_buff_on(req):
    def on(state, g):
        index = int(req.get("GuildBuffIndex") or 0)
        row = next((r for r in table_rows("GuildBuffTable") if r["guildBuffIndex"] == index), None)
        if row is None or g.get("fund", 0) < row["needActiveCost"]:
            return {"ResultCode": 1, "ResultMessage": "not enough guild funds"}
        g["fund"] -= row["needActiveCost"]
        g.setdefault("buffs", {})[str(index)] = now_ms() + row["guildBuffKeepMinute"] * 60_000
        return ok(OperationAmount=g["fund"], GuildBuffInfo={"GuildBuffIndex": index,
                                                            "ExpireTime": g["buffs"][str(index)]})
    return with_guild(on)


@api("guild/donationGoods")
def guild_donation_goods(req):
    def donate(state, g):
        amount = max(0, min(int(req.get("DonationAmount") or 0), donation_limit(g) - guild_today(g)["donated"]))
        before = guild_level(g.get("exp", 0))[0]
        spend_gold(state, amount)
        g["fund"] = g.get("fund", 0) + amount
        g["donated"] = g.get("donated", 0) + amount
        g["exp"] = g.get("exp", 0) + int(amount * config_number(20043))
        g["contribution"] = g.get("contribution", 0) + int(amount * config_number(20044))
        guild_today(g)["donated"] += amount
        guild_week(g)["donated"] += amount
        return ok(AccountMoney=money(state), GuildLevelInfo=guild_level_info(g, before),
                  MyGuildInfo={"Donation": g["contribution"], "DonationAmount": guild_today(g)["donated"],
                               "OperationAmount": g["fund"], "DonationItem": 0,
                               "TotalDonation": guild_week(g)["donated"]})
    return with_guild(donate)


@api("guild/joinType")
def guild_join_type(req):
    def change(state, g):
        g.update(joinType=int(req.get("JoinType") or 0), open=bool(req.get("Open", True)),
                 joinLevelLimit=int(req.get("JoinLevelLimit") or 0), donationLimit=int(req.get("DonationLimit") or 0))
        return ok(JoinType=g["joinType"], Open=g["open"], JoinLevelLimit=g["joinLevelLimit"],
                  DonationLimit=donation_limit(g))
    return with_guild(change)


@api("guild/withdrawal")
@api("guild/close")
def guild_leave(req):
    """leaving or disbanding: the guild is the player's alone, so both end it"""
    with _lock:
        state = load_state()
        if state is not None and state.pop("guild", None) is not None:
            save_state(state)
    return ok(GuildDetailInfo={"GuildNo": 0, "PenaltyExpireTime": 0, "GuildJoinRequestCount": 0})


# ---------------------------------------------------------------- Guild Raid (guildDungeon/*; tools/gen_guild.py)
# Real (recon/guild_research.md): Omega Rugal and Nightmare Geese rotate weekly; at most 2 keys, a used key comes
# back 6 hours later (the timer starts at the first use and is frozen at 2); the boss's HP is the guild's
# (in battle: max HP - DungeonScore.score, Model_GuildDungeon.SetBossHP); a difficulty whose damage reached the
# boss's HP is defeated (ClearBossIndexList) and stays open for more damage. Offline the guild's damage is the
# player's. save.json guild "raid": season, keys, keyAt (next key, 0 when full), scores / best by difficulty index.
RAID_EPOCH = 1704067200000                     # 2024-01-01 00:00 UTC, a Monday: season 1 (ours)
WEEK_MS, RAID_KEY_MAX, RAID_KEY_MS = 7 * 86_400_000, 2, 6 * 3_600_000
GUILD_DUNGEON = 8                               # EDungeonType.GuildDungeon: OperateSchedule.SubCategory of the raid


def raid_season():
    """(season, start, end): weekly seasons from RAID_EPOCH; a season's damage and clears start again"""
    season = (now_ms() - RAID_EPOCH) // WEEK_MS + 1
    start = RAID_EPOCH + (season - 1) * WEEK_MS
    return season, start, start + WEEK_MS - 1


def raid_groups():
    """the open bosses: the real game rotated Omega Rugal / Nightmare Geese weekly (and ran its guest bosses as
    events); user, 2026-11-02: "I want all boss to be active all the time" - every GuildBossGroupTable boss, every week"""
    return sorted(r["guildBossGroupIndex"] for r in table_rows("GuildBossGroupTable"))


def raid_group_of(boss):
    return next((d["guildBossGroup"] for d in table_rows("GuildBossDifficultyTable")
                 if d["guildBossDifficultyIndex"] == boss), 0)


def raid_keys(r, group):
    """a boss's keys: at most 2, a used one back 6 h later (the timer starts at the first use)"""
    g = str(group)
    keys, at = r["keys"].setdefault(g, RAID_KEY_MAX), r["keyAt"].setdefault(g, 0)
    while keys < RAID_KEY_MAX and at and now_ms() >= at:
        keys += 1
        at = at + RAID_KEY_MS if keys < RAID_KEY_MAX else 0
    r["keys"][g], r["keyAt"][g] = keys, at
    return keys


def raid_use_key(r, group):
    g = str(group)
    if raid_keys(r, group) <= 0:
        return False
    if r["keys"][g] == RAID_KEY_MAX:
        r["keyAt"][g] = now_ms() + RAID_KEY_MS
    r["keys"][g] -= 1
    return True


def raid_state(g):
    """save.json guild "raid": this season's damage per difficulty row (scores, best, plays, cleared) and the keys per
    boss group (kept across seasons; one shared count before every boss was open)"""
    season = raid_season()[0]
    r = g.get("raid") or {}
    keys, key_at = r.get("keys", {}), r.get("keyAt", {})
    if not isinstance(keys, dict):
        keys, key_at = {str(x): keys for x in raid_groups()}, {str(x): key_at or 0 for x in raid_groups()}
    if r.get("season") != season:
        r = {"season": season, "scores": {}, "best": {}, "plays": {}, "cleared": []}
    r["keys"], r["keyAt"] = keys, key_at
    g["raid"] = r
    return r


def raid_schedules():
    """the raid selector card shows each boss's time left from its dungeon schedule (DungeonController.
    GetDungeonSchedule(GuildDungeon, boss group)); without one it threw a NullReferenceException"""
    season, start, end = raid_season()
    return [apidefaults.default("OperateSchedule", Version=1, Category=DUNGEON_CATEGORY, SubCategory=GUILD_DUNGEON,
                                Index=group, Detail=apidefaults.default(
                                    "OperateScheduleData", SubGroup=[group], StartTs=start // 1000,
                                    EndTs=(end + 1) // 1000, OffOnSched=TIMED_SCHEDULE))
            for group in raid_groups()]


def raid_season_info(group):
    season, start, end = raid_season()
    return {"bossGroup": group, "season": season, "seasonStartDate": start, "seasonEndDate": end}


def raid_season_list():
    return [raid_season_info(group) for group in raid_groups()]


def raid_dungeon_info(r, group):
    keys = raid_keys(r, group)
    nxt = r["keyAt"].get(str(group)) or 0
    return {"ticket": keys, "paymentPlayCount": 0, "ticketRefreshTime": nxt - RAID_KEY_MS if nxt else 0,
            "nextTicketRefreshTime": nxt}


def raid_score(r, boss):
    s = r["scores"].get(str(boss), 0)
    return {"bossIndex": boss, "score": s, "myScore": s}


def raid_boss_hp(boss):
    """max HP of the difficulty's boss: its MonsterGrowthTable row (gen_guild gives the level row 0)"""
    d = next((x for x in table_rows("GuildBossDifficultyTable") if x["guildBossDifficultyIndex"] == boss), None)
    m = d and next((x for x in table_rows("MonsterTable") if x["monsterIndex"] == d["guildBossMonster"]), None)
    gr = m and next((x for x in table_rows("MonsterGrowthTable") if x["growthType"] == m["growthType"]
                     and x["grade"] == m.get("monsterType", 3)), None)
    return int(gr["maxHPBase"]) if gr else 0


def raid_add(r, boss, damage):
    key = str(boss)
    r["scores"][key] = r["scores"].get(key, 0) + damage
    r["plays"][key] = r["plays"].get(key, 0) + 1
    best = damage > r["best"].get(key, 0)
    if best:
        r["best"][key] = damage
    hp = raid_boss_hp(boss)
    if hp and r["scores"][key] >= hp and boss not in r["cleared"]:
        r["cleared"].append(boss)
    return best


@api("guildDungeon/lobby")
def guild_dungeon_lobby(req):
    def lobby(state, g):
        r = raid_state(g)
        group = int(req.get("BossGroup") or raid_groups()[0])
        bosses = [d["guildBossDifficultyIndex"] for d in table_rows("GuildBossDifficultyTable") if d["guildBossGroup"] == group]
        return ok(ClearBossIndexList=r["cleared"], DungeonScoreList=[raid_score(r, b) for b in bosses],
                  DungeonInfo=raid_dungeon_info(r, group), SeasonInfo=raid_season_info(group), SeasonResultList=[])
    return with_guild(lobby)


@api("guildDungeon/playStart")
def guild_dungeon_play_start(req):
    def start(state, g):
        r = raid_state(g)
        boss = int(req.get("BossIndex") or 0)
        group = int(req.get("BossGroup") or raid_group_of(boss))
        if not raid_use_key(r, group):
            return {"ResultCode": 1, "ResultMessage": "no key"}
        r["playing"] = boss
        return ok(PlayToken=now_ms(), DungeonInfo=raid_dungeon_info(r, group), DungeonScore=raid_score(r, boss))
    return with_guild(start)


@api("guildDungeon/playEnd")
def guild_dungeon_play_end(req):
    def end(state, g):
        r = raid_state(g)
        boss = r.pop("playing", 0)
        best = raid_add(r, boss, max(0, int(req.get("Score") or 0))) if boss else False
        return ok(AccountMoney=money(state), DungeonInfo=raid_dungeon_info(r, raid_group_of(boss)),
                  DungeonScore=raid_score(r, boss), BestScoreRenew=best, ResultRank=1)
    return with_guild(end)


@api("guildDungeon/playMopup")
def guild_dungeon_play_mopup(req):
    """auto-clear: each run repeats the best damage on that difficulty and uses a key"""
    def mopup(state, g):
        r = raid_state(g)
        boss = int(req.get("BossIndex") or 0)
        group = int(req.get("BossGroup") or raid_group_of(boss))
        for _ in range(max(1, int(req.get("MopupCount") or 1))):
            if not r["best"].get(str(boss)) or not raid_use_key(r, group):
                break
            raid_add(r, boss, r["best"][str(boss)])
        return ok(AccountMoney=money(state), DungeonInfo=raid_dungeon_info(r, group), DungeonScore=raid_score(r, boss),
                  ResultRank=1, RemainItemList=[])
    return with_guild(mopup)


@api("guildDungeon/ranking")
def guild_dungeon_ranking(req):
    def ranking(state, g):
        r = raid_state(g)
        boss = str(int(req.get("BossIndex") or 0))
        if not r["scores"].get(boss):
            return ok(nameList=[], playList=[])
        return ok(nameList=[{"usn": USN, "nickName": state["nickname"]}],
                  playList=[{"usn": USN, "clearCount": r["plays"].get(boss, 0), "score": r["scores"][boss],
                             "bestScore": r["best"].get(boss, 0), "rankingTime": now_ms(), "attackCount": r["plays"].get(boss, 0)}])
    return with_guild(ranking)


# ---------------------------------------------------------------- Colossal Invasion (guildCoop; tools/gen_colossal.py)
# The guild's tier (1-50) against the Wary Colossal: guildCoop/lobby shows it (DungeonScore step / score / attackCount,
# DungeonInfo plays used today), playStart enters it (up to QuestEventTable.limitPlayValue1 plays a day), playEnd adds
# the damage to the tier, pays the day's first play (GuildCoopTable.firstPlayReward) and clears the tier once its damage
# reaches GuildCoopStageGroupTable.stageClearScore (stageClearReward paid, the next tier opened). Coins are guild coins
# (AccountMoney.GuildCoin). Seasons are the raid's weekly ones (ours). save.json guild "coop".
COOP_GROUP, COOP_TIERS = 1, 50


def coop_row():
    return next((r for r in table_rows("GuildCoopTable") if r["guildCoopIndex"] == COOP_GROUP), {})


def coop_tier(step):
    group = coop_row().get("guildCoopStageGroup", COOP_GROUP)
    return next((r for r in table_rows("GuildCoopStageGroupTable")
                 if r["guildCoopStageGroup"] == group and r["stageCount"] == step), {})


def coop_daily_limit():
    event = coop_row().get("questEventIndex", 0)
    return next((int(r.get("limitPlayValue1") or 0) for r in table_rows("QuestEventTable")
                 if r["questEventIndex"] == event), 0) or 3


def coop_state(g):
    season = raid_season()[0]
    c = g.get("coop") or {}
    if c.get("season") != season:
        c = {"season": season, "step": 1, "steps": {}, "recharges": 0}
    day = soul_day()
    if c.get("day") != day:
        c.update(day=day, plays=0, firstPaid=False, recharges=0)
    g["coop"] = c
    return c


def coop_step(c, step=None):
    key = str(step or c["step"])
    return c["steps"].setdefault(key, {"score": 0, "attacks": 0, "best": 0, "clear": False})


def coop_score(c):
    s = coop_step(c)
    return {"step": c["step"], "score": s["score"], "attackCount": s["attacks"], "lastCoop": c["step"] >= COOP_TIERS
            and s["clear"]}


def coop_info(c):
    return {"useTicketCount": c["plays"], "rechargeCount": c["recharges"]}


def coop_season_info():
    season, start, end = raid_season()
    return {"bossGroup": COOP_GROUP, "season": season, "seasonStartDate": start, "seasonEndDate": end}


def pay_coins(state, group):
    """a coin RewardGroupTable group (gen_colossal: guild coins) into the wallet -> RewardContents"""
    out, wallet = [], regen_ap(state)
    for r in table_rows("RewardGroupTable"):
        if r.get("rewardGroup") == group and group:
            count = r.get("contentsCountMin", 0)
            wallet["GuildCoin"] = int(wallet.get("GuildCoin", 0)) + count
            out.append(reward(r.get("rewardType", 0), count))
    return out


@api("guildCoop/lobby")
def guild_coop_lobby(req):
    def lobby(state, g):
        c = coop_state(g)
        return ok(DungeonScore=coop_score(c), DungeonInfo=coop_info(c), SeasonInfo=coop_season_info(),
                  SeasonResultList=[], StepClearRewardList=[])
    return with_guild(lobby)


@api("guildCoop/playStart")
def guild_coop_play_start(req):
    def start(state, g):
        c = coop_state(g)
        if c["plays"] >= coop_daily_limit():
            return {"ResultCode": 1, "ResultMessage": "no plays left today"}
        c["plays"] += 1
        c["playing"] = int(req.get("Step") or c["step"])
        return ok(PlayToken=now_ms(), DungeonScore=coop_score(c))
    return with_guild(start)


@api("guildCoop/playEnd")
def guild_coop_play_end(req):
    def end(state, g):
        c = coop_state(g)
        step = c.pop("playing", c["step"])
        damage = max(0, int(req.get("Score") or 0))
        s = coop_step(c, step)
        s["score"] += damage
        s["attacks"] += 1
        best = damage > s["best"]
        s["best"] = max(s["best"], damage)
        rewards = []
        if not c["firstPaid"]:
            c["firstPaid"] = True
            rewards += pay_coins(state, coop_row().get("firstPlayReward", 0))
        tier = coop_tier(step)
        if tier and not s["clear"] and s["score"] >= tier.get("stageClearScore", 0) > 0:
            s["clear"] = True
            rewards += pay_coins(state, tier.get("stageClearReward", 0))
            if step == c["step"] and c["step"] < COOP_TIERS:
                c["step"] += 1
        left = max(0, coop_daily_limit() - c["plays"])
        return ok(AccountMoney=money(state), DungeonInfo={"ticket": left, "paymentPlayCount": 0, "ticketRefreshTime": 0,
                                                          "nextTicketRefreshTime": 0},
                  DungeonScore={"bossIndex": step, "score": s["score"], "myScore": s["score"]}, BestScoreRenew=best,
                  FirstClearRewardList=rewards)
    return with_guild(end)


@api("guildCoop/recharge")
def guild_coop_recharge(req):
    """more plays for today (ours: free)"""
    def recharge(state, g):
        c = coop_state(g)
        c["plays"], c["recharges"] = 0, c["recharges"] + 1
        return ok(AccountMoney=money(state), DungeonInfo=coop_info(c))
    return with_guild(recharge)


@api("guildCoop/memberRanking")
def guild_coop_member_ranking(req):
    def ranking(state, g):
        c = coop_state(g)
        total = sum(s["score"] for s in c["steps"].values())
        if not total:
            return ok(NameList=[], PlayList=[])
        attacks = sum(s["attacks"] for s in c["steps"].values())
        return ok(NameList=[{"usn": USN, "nickName": state["nickname"]}],
                  PlayList=[{"usn": USN, "clearCount": sum(1 for s in c["steps"].values() if s["clear"]),
                             "score": total, "bestScore": max(s["best"] for s in c["steps"].values()),
                             "rankingTime": now_ms(), "attackCount": attacks}])
    return with_guild(ranking)


@api("guildCoop/guildRanking")
@api("guildCoop/seasonResultHistory")
def guild_coop_empty(req):
    return ok()


@api("guildDungeon/guildRanking")
def guild_dungeon_guild_ranking(req):
    season = raid_season()[0]
    return ok(minSeason=season, maxSeason=season, rankingList=[])


@api("guild/history")
@api("guild/greetList")
@api("guild/noticeList")
@api("guild/boardList")
@api("guild/recommandList")
@api("guild/find")
@api("guild/joinRequestList")
def guild_empty_list(req):
    """no other players offline: no other guilds, members, greetings, posts or history to show"""
    return ok()


@api("core/coreAcquireAll")
def core_acquire_all(req):
    def reachable(c, trees, have):
        level = fighter_level(c["index"], c.get("exp", 0))
        spots = {r["coreSpotIndex"]: r.get("unlockLevel", 0) for r in table_rows("CoreSpotTable")}
        return [i for i, r in trees.items() if spots.get(r["coreSpotIndex"], 0) <= level]
    return acquire_cores(req, reachable)


# ---------------------------------------------------------------- Soul Quest (fighterQuest/*; recon/soulquest_spec.md)
# A 1v1 mode: the player picks one of their fighters (a FighterQuestTable row, fighterQuestIndex = 1_000_000 *
# difficultyNo + characterIndex; NORMAL 1 / HARD 2 / EXPERT 3), randomPick draws an enemy row of the same difficulty,
# playStart spends Soul Tokens (the client's Account.Point; usePointValue a run) and playEnd pays. The client never
# recalculates the tokens (recon/soulquest_client.md section 4): playInfo / playStart / giveUp / mopUp each return the
# authoritative Point. Real rules: 3 tokens a day (MaxPoint), an extra run costs 40 rubies (ChargeCount, up to
# ContentsAdmissionTable 8's limit), first clear NORMAL 15 rubies + 3 souls, HARD 18 + 3, EXPERT 23 + 9, repeat clears
# 1 / 2 / 5 souls of the player's own fighter (item 200000 + fighter). Ours: 5 extra runs a day, a given-up or lost
# run is not refunded, account EXP as a story win, no star-mission rewards, mop-up needs no ticket.
# save.json "soulQuest": {"day", "point", "charges", "stages": {"<fighterQuestIndex>": {"result", "missions"}},
# "current": {"mine", "enemy", "picks", "token"}} (+ "pickReset": the re-rolls so far, until playStart). The amounts
# live in tables/data/soulquest_rewards.json (tools/gen_soulquest.py); these defaults apply when it is missing.
SQ_DIFFICULTY_STEP = 1_000_000
SQ_DEFAULTS = {"maxPoint": 3, "extraPrice": 40, "extraMax": 5,
               "1": {"firstRubies": 15, "firstSouls": 3, "souls": 1},
               "2": {"firstRubies": 18, "firstSouls": 3, "souls": 2},
               "3": {"firstRubies": 23, "firstSouls": 9, "souls": 5}}
SQ_ALL_CLEAR_RUBIES = 10    # bonus rubies for clearing all three star missions the first time (ours)
SQ_MOPUP_TICKET = AUTO_CLEAR_TICKET   # ConfigTable 132 = this SKIP TICKET item (1302), MopUpCostTable 1: one a run


def sq_config():
    try:
        got = json.load(open(os.path.join(TABLES, "soulquest_rewards.json"), encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        got = {}
    return {k: {**v, **got.get(k, {})} if isinstance(v, dict) else got.get(k, v) for k, v in SQ_DEFAULTS.items()}


def sq_row(index):
    """The FighterQuestTable row, or a stand-in when the table is missing (usePointValue 1, own fighter)."""
    row = next((r for r in table_rows("FighterQuestTable") if r.get("fighterQuestIndex") == index), None)
    return row or {"fighterQuestIndex": index, "playerFighterIndex": index % SQ_DIFFICULTY_STEP, "usePointValue": 1}


def sq_fighter(index):
    row = sq_row(index)
    return int(row.get("playerFighterIndex") or row.get("fighterIndex") or index % SQ_DIFFICULTY_STEP)


def sq_state(state):
    """save.json "soulQuest" for today: a new day (soul_day, the 5:00 reset) refills the tokens to maxPoint and clears
    the extra runs bought."""
    s = state.setdefault("soulQuest", {})
    if s.get("day") != soul_day() or "point" not in s:
        s.update(day=soul_day(), point=sq_config()["maxPoint"], charges=0)
    s.setdefault("stages", {})
    return s


def sq_soul_item(fighter):
    """The soul item of a fighter, or 0 when it has none (ItemTable; a missing table allows every fighter)."""
    item = SOUL_ITEM_BASE + fighter
    rows = table_rows("ItemTable")
    return item if not rows or any(r.get("itemIndex") == item for r in rows) else 0


def sq_mission_slots(entry):
    return entry.setdefault("missions", [0, 0, 0])


def sq_play_info(s):
    cur = s.get("current") or {}
    return apidefaults.default("FighterQuestPlayInfo", PointUpdateTime=now_ms(), Point=s["point"],
                               MaxPoint=sq_config()["maxPoint"], FighterQuestIndex=cur.get("mine", 0),
                               MonsterFighterQuestIndex=cur.get("enemy", 0), PickResetCount=cur.get("picks", 0),
                               ChargeCount=s["charges"])


def sq_stage_entry(index, entry):
    m = sq_mission_slots(entry)
    return apidefaults.default("FighterQuest", FighterQuestIndex=int(index), BattleResult=entry.get("result", 0),
                               Mission1Index=m[0], Mission2Index=m[1], Mission3Index=m[2])


def sq_fail(message):
    return {"ResultCode": 1, "ResultMessage": message}


@api("fighterQuest/playInfo")
def fighter_quest_play_info(req):
    with _lock:
        state = load_state()
        s = sq_state(state)
        save_state(state)
    return ok(ServerUtcTime=now_ms(), PlayInfo=sq_play_info(s))


@api("fighterQuest/playList")
def fighter_quest_play_list(req):
    """only the stages played so far (the client has defaults for the rest)"""
    with _lock:
        state = load_state()
        s = sq_state(state)
        save_state(state)
    return ok(ServerUtcTime=now_ms(), PlayList=[sq_stage_entry(k, e) for k, e in s["stages"].items()],
              PickupPlayList=[])


@api("fighterQuest/pickupPlayList")
def fighter_quest_pickup_play_list(req):
    return ok(PickupPlayList=[])


@api("fighterQuest/randomPick")
def fighter_quest_random_pick(req):
    """an enemy row of the same difficulty, random, not the player's own fighter if possible"""
    mine = int(req.get("FighterQuestIndex") or 0)
    step = mine // SQ_DIFFICULTY_STEP
    rows = [r["fighterQuestIndex"] for r in table_rows("FighterQuestTable")
            if r.get("fighterQuestIndex", 0) // SQ_DIFFICULTY_STEP == step]
    others = [i for i in rows if i != mine and sq_fighter(i) != sq_fighter(mine)]
    enemy = random.choice(others or rows or [mine])
    with _lock:
        state = load_state()
        s = sq_state(state)
        s["pickReset"] = int(req.get("PickResetCount") or 0)
        save_state(state)
    return ok(AccountMoney=money(state), MonsterFighterQuestIndex=enemy)


@api("fighterQuest/playStart")
def fighter_quest_play_start(req):
    """spend the row's usePointValue tokens and remember the match (playInfo then reports it in progress)"""
    mine, enemy = int(req.get("FighterQuestIndex") or 0), int(req.get("MonsterFighterQuestIndex") or 0)
    row = sq_row(mine)
    cost = int(row.get("usePointValue") or 1)
    with _lock:
        state = load_state()
        s = sq_state(state)
        need = int(row.get("fighterQuestOpenCondition") or 0)   # real: HARD needs the fighter's NORMAL clear, EXPERT its HARD
        if need and s["stages"].get(str(need), {}).get("result") != 1:
            return sq_fail("stage locked")
        if s["point"] < cost:
            return sq_fail("not enough Soul Tokens")
        s["point"] -= cost
        token = now_ms()
        s["current"] = {"mine": mine, "enemy": enemy, "picks": s.pop("pickReset", 0), "token": token}
        save_state(state)
    return ok(QuestPlayToken=token, DropBossList=[], BonusMap=False, Point=s["point"])


def sq_fighters(state, req, index, won, runs=1):
    """The Soul Quest requests carry the fighter used as `Character` (CharacterSimple6), not a CharacterList; give it
    STORY_FIGHTER_EXP_DEFAULT a win (ours) and return the reply's CharacterList."""
    c = req.get("Character") or {}
    fighter_index = int(c.get("CharacterIndex") or 0) or sq_fighter(index)
    if not fighter_index:
        return []
    # a fighter owned only through ownAllFighters has no saved record: start from the exp the client shows
    # (owned_characters: default / "unlimited" level), like the story stage end, and never lower a level
    base = next((int(o.get("exp", 0)) for o in owned_characters(state) if o["index"] == fighter_index), 0)
    fighter = character_state(state, fighter_index)
    fighter["exp"] = (max(fighter.get("exp", 0), base, int(c.get("Exp") or 0))
                      + (STORY_FIGHTER_EXP_DEFAULT * runs if won else 0))
    return [simple(fighter, "CharacterSimple", start_grades())]


def sq_pay(state, s, index, runs, first):
    """Pay `runs` clears of stage `index` (+ the first-clear bonus). -> (FirstClearRewardList, souls gained, souls a
    repeat run, soul item). Rubies go into the wallet, souls into the inventory (the player's own fighter, if it has a soul item)."""
    cfg = sq_config()[str(min(3, max(1, index // SQ_DIFFICULTY_STEP)))]
    item = sq_soul_item(sq_fighter(index))
    first_list, souls = [], cfg["souls"] * runs
    if first:
        if cfg["firstRubies"]:
            wallet = regen_ap(state)
            wallet["Cash"] = int(wallet.get("Cash", 0)) + cfg["firstRubies"]
            first_list.append(reward(RUBY_GOODS, cfg["firstRubies"]))
        souls = cfg["firstSouls"] + cfg["souls"] * (runs - 1)    # the first clear pays its bonus instead
        if item:
            first_list.append(reward(ITEM_GOODS, cfg["firstSouls"], item))
    if item and souls:
        inv = items(state)
        inv[str(item)] = int(inv.get(str(item), 0)) + souls
    return first_list, (souls if item else 0), cfg["souls"] if item else 0, item


@api("fighterQuest/playEnd")
def fighter_quest_play_end(req):
    index, result = int(req.get("FighterQuestIndex") or 0), int(req.get("BattleResult") or 0)
    won = result == WIN
    with _lock:
        state = load_state()
        s = sq_state(state)
        cur = s.get("current") or {}
        token = int(req.get("QuestPlayToken") or 0)
        if cur.get("mine") != index or (token and cur.get("token") and token != cur["token"]):
            return sq_fail("no match in progress")
        s.pop("current", None)
        entry = s["stages"].setdefault(str(index), {"result": 0, "missions": [0, 0, 0]})
        first = won and entry["result"] == 0
        first_list, gained, item, rank, all_clear = [], [], 0, (0, []), False
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before
        if won:
            entry["result"] = 1
            got = sq_mission_slots(entry)       # the star missions met so far
            met = [int(req.get(f"Mission{i}Index") or 0) for i in (1, 2, 3)]
            new_missions = [m for m, g in zip(met, got) if m and not g]
            got[:] = [g or m for g, m in zip(got, met)]
            groups = {r["stageMissionIndex"]: r.get("missionCompleteRewardGroup", 0) for r in table_rows("StageMissionTable")}
            for m in new_missions:              # each mission pays its reward group (rubies) the first time it is met
                give_rewards(state, groups.get(m, 0))
            first_list, souls, _, item = sq_pay(state, s, index, 1, first)
            if souls and item:
                gained = [{"ItemIndex": item, "Qty": souls, "Lock": 0, "UpdateTime": now_ms()}]
            # "Clear every mission to earn bonus Rubies" (the client's popup): the first time all three are met
            all_clear = all(got) and not entry.get("allClear")
            entry["allClear"] = bool(entry.get("allClear") or all_clear)
            if all_clear:
                regen_ap(state)["Cash"] = int(regen_ap(state).get("Cash", 0)) + SQ_ALL_CLEAR_RUBIES
            state["exp"] = before + STORY_ACCOUNT_EXP
            rank = apply_rank_up(state, before)
        characters = sq_fighters(state, req, index, won)
        shown = list(first_list)
        if gained and not first:
            shown.append(reward(ITEM_GOODS, gained[0]["Qty"], item))
        save_state(state)
    # The RESULT screen's REWARDS list is built client-side from RewardBattleCardList, the StageReward boss drops and
    # GlobalDropRewardList (Parse_FighterQuestStageEnd); RewardItemList / FirstClearRewardList only update the
    # inventory / the first-clear slot, so the goods to show go into GlobalDropRewardList (display only).
    # Mission1-3RewardList give the YOU WIN mission rows their reward cell: UIUnit_MissionReward.SetRewardData HIDES a row
    # whose reward has count 0 (blank rows), so each row lists its StageMissionTable.missionCompleteRewardGroup.
    # Clear Time and the leader EXP are computed by the client (the EXP popup only follows the current team deck).
    missions = {}
    if won:
        row = sq_row(index)
        missions = mission_reward_lists([row.get(f"mission{i}Index", 0) for i in (1, 2, 3)], got,
                                        lambda m: reward_contents(groups.get(m, 0)))
    return ok(FighterQuestIndex=index, BattleResult=result, FirstClearFlag=1 if first else 0,
              AccountLevelUpFlag=rank[0], AccountMoney=money(state),
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]),
              CharacterList=characters,
              RewardItemList=gained, FirstClearRewardList=first_list, GlobalDropRewardList=shown,
              MissionAllRewardList=[reward(RUBY_GOODS, SQ_ALL_CLEAR_RUBIES)] if all_clear else [],
              AccountLevelUpRewardList=rank[1], **missions)


@api("fighterQuest/giveUp")
def fighter_quest_give_up(req):
    """abandon the match in progress; the tokens spent are not refunded (ours)"""
    with _lock:
        state = load_state()
        s = sq_state(state)
        s.pop("current", None)
        s.pop("pickReset", None)
        save_state(state)
    return ok(Point=s["point"])


@api("fighterQuest/charge")
def fighter_quest_charge(req):
    """buy one extra run: extraPrice rubies (free for a test player), ChargeCount + 1, Point + 1"""
    cfg = sq_config()
    with _lock:
        state = load_state()
        s = sq_state(state)
        wallet = regen_ap(state)
        if s["charges"] >= cfg["extraMax"]:
            return sq_fail("no extra runs left today")
        if not state.get("unlimited"):
            if int(wallet.get("Cash", 0)) < cfg["extraPrice"]:
                return sq_fail("not enough rubies")
            wallet["Cash"] = int(wallet["Cash"]) - cfg["extraPrice"]
        s["charges"] += 1
        s["point"] += 1
        save_state(state)
    return ok(ChargeCount=s["charges"], AccountMoney=money(state))


@api("fighterQuest/fighterQuestMopUp")
def fighter_quest_mop_up(req):
    """AUTO-CLEAR of a cleared stage: per run usePointValue Soul Tokens + the MopUpCostTable row's tickets (the SKIP TICKET,
    ConfigTable 132), the repeat souls a run; no first clear, no missions"""
    index, count = int(req.get("FighterQuestIndex") or 0), max(0, int(req.get("StageMopUpCount") or 0))
    cost = int(sq_row(index).get("usePointValue") or 1) * count
    with _lock:
        state = load_state()
        s = sq_state(state)
        if not count or s["stages"].get(str(index), {}).get("result") != 1:
            return sq_fail("stage not cleared")
        if s["point"] < cost:
            return sq_fail("not enough Soul Tokens")
        inv = items(state)
        per_run = next((int(r.get("mopUpMaterialCount") or 1) for r in table_rows("MopUpCostTable")
                        if r.get("mopUpCostIndex") == sq_row(index).get("mopUpCostIndex")), 1)
        if int(inv.get(str(SQ_MOPUP_TICKET), 0)) < per_run * count:
            return sq_fail("not enough Skip Tickets")
        inv[str(SQ_MOPUP_TICKET)] = int(inv.get(str(SQ_MOPUP_TICKET), 0)) - per_run * count
        s["point"] -= cost
        _, souls, per_run_souls, item = sq_pay(state, s, index, count, False)
        before = max(state.get("exp", 0), int((req.get("PlayerAccount") or {}).get("Exp") or 0))
        state["exp"] = before + STORY_ACCOUNT_EXP * count
        rank = apply_rank_up(state, before)
        characters = sq_fighters(state, req, index, True, count)
        ticket = {"ItemIndex": SQ_MOPUP_TICKET, "Qty": int(items(state).get(str(SQ_MOPUP_TICKET), 0)), "Lock": 0,
                  "UpdateTime": now_ms()}
        save_state(state)
    contents = [mopup_reward(ITEM_GOODS, per_run_souls, run, item) for run in range(1, count + 1)] if item else []
    return ok(FighterQuestIndex=index, AccountLevelUpFlag=rank[0], Point=s["point"], RewardContentsList=contents,
              RewardItemList=[{"ItemIndex": item, "Qty": souls, "Lock": 0, "UpdateTime": now_ms()}] if item else [],
              PlayerAccount=apidefaults.default("PlayerAccount", Usn=USN, Exp=state["exp"]), AccountMoney=money(state),
              CharacterList=characters,
              MopupTicketItem=ticket, AccountLevelUpRewardList=rank[1])


# ---------------------------------------------------------------- Team Relay (relayDungeon/*; recon/teamrelay_spec.md)
# Five giant bosses (TeamRelayTable 501-505, tools/gen_teamrelay.py), up to 5 teams of 3 fight one after another
# against ONE boss in playTime seconds; the score is the total damage (BestRecord = max). Client side (recon/
# teamrelay_client.md): Send_TeamRelayList / _Info / _TeamDeckUpdate / _Start / _End / _Recharge / _Mopup. The list
# shows only bosses whose OperateSchedule (Category 2, SubCategory 6, Index = teamRelayIndex) came in player/poll
# (DungeonController.GetTeamRelayDungeons); a tile is "not open" unless seasonStartTime..seasonEndTime brackets now.
# Real: 3 entries a week per boss, +1 team after each failed run up to 5, an extra entry 300 rubies (the real game's
# screenshot; PLAN's 150 conflicts). Ours: the week resets Monday 05:00 (the game's daily reset hour), a reset also
# clears best / teams / paid rewards, a run counts as cleared only when the client says BattleResult WIN (its
# BattleResult codes are unverified, so a killed boss reported as 0 also gives a team), boss HP is full each attempt
# (bossHPResetType 1; BossHP is only echoed), rewards are TeamRelayRewardTable rows by total damage, each paid once a
# week (play group by this run's damage, best group by the best record), rankings are empty (no other players).
# save.json "teamRelay": {"week", "bosses": {"<teamRelayIndex>": {"point", "recharge", "best", "bestTime", "deckCount",
# "decks": [TeamRelayCharacter...], "rewards": [paid BEST-record TeamRelayRewardTable indexes], "plays", "last",
# "cleared"}}, "current": {"boss", "token"}}. Amounts live in tables/data/teamrelay.json (tools/gen_teamrelay.py);
# these defaults apply when it is missing. Two modes (teamrelay.json "modes", TeamRelayTable.modeIndex): 501 Dungeon
# (3 entries a week, extra entry 300 rubies) and 502 Challenge (1 entry, 100 rubies; video jGrTKPbst4I). Entries per
# week = the boss row's weeklyPlayableCount, the extra-entry price = the boss's mode. Rewards: the play group
# (playRewardGroup) pays EVERY run for the highest threshold reached (tools/gen_teamrelay.py), the best-record group
# (bestRecordRewardGroup) pays each threshold once a week. Quitting (the pause menu's surrender, BattleResult 2 in
# Send_TeamRelayEnd) does not count the attempt (Orochinagi guide): the entry comes back, nothing is paid or recorded.
TEAM_RELAY_DUNGEON = 6      # EDungeonType.TeamRelay: OperateSchedule.SubCategory
TR_DEFAULTS = {"bosses": [501, 502, 503, 504, 505], "weekly": 3, "extraPrice": 300, "maxTeams": 5,
               "resetWeekday": 0, "resetHour": 5,
               "modes": {"501": {"extraPrice": 300, "weekly": 3}, "502": {"extraPrice": 100, "weekly": 1}}}
TR_QUIT = 2     # RelayDungeonEndRequest.BattleResult of a surrender (Send_TeamRelayEnd: InGameManager+0x7a -> 2; else
                # (param_4 & 1) ^ 1, so 0 / 1 are the normal ends, 0 seen on a time-out)
TR_BOSS_HP = 100_000_000    # BossHP echoed in the replies (ours; the client ignores it while bossHPResetType is 1)


def tr_config():
    try:
        got = json.load(open(os.path.join(TABLES, "teamrelay.json"), encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        got = {}
    return {**TR_DEFAULTS, **got, "modes": {**TR_DEFAULTS["modes"], **got.get("modes", {})}}


def tr_week():
    """(label, start ms, end ms) of the current week: it starts on resetWeekday (0 = Monday) at resetHour local time"""
    cfg = tr_config()
    tm = time.localtime(time.time() - cfg["resetHour"] * 3600)
    back = (tm.tm_wday - cfg["resetWeekday"]) % 7
    start = time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday - back, cfg["resetHour"], 0, 0, 0, 0, -1))
    end = time.mktime((tm.tm_year, tm.tm_mon, tm.tm_mday - back + 7, cfg["resetHour"], 0, 0, 0, 0, -1))
    return time.strftime("%G-W%V", time.localtime(start)), int(start * 1000), int(end * 1000)


def tr_season(start):
    return (start - RAID_EPOCH + WEEK_MS // 2) // WEEK_MS + 1


def tr_bosses():
    """every boss of every mode: teamrelay.json "bosses" plus the TeamRelayTable rows"""
    return sorted({int(b) for b in tr_config()["bosses"]} | {r["teamRelayIndex"] for r in table_rows("TeamRelayTable")
                                                              if r.get("teamRelayIndex")})


def tr_mode(boss):
    return int(tr_row("TeamRelayTable", "teamRelayIndex", boss).get("modeIndex") or 501)


def tr_weekly(boss):
    """entries a week: the boss row's weeklyPlayableCount, else the mode's config, else the global one"""
    cfg = tr_config()
    row = tr_row("TeamRelayTable", "teamRelayIndex", boss)
    return int(row.get("weeklyPlayableCount") or cfg["modes"].get(str(tr_mode(boss)), {}).get("weekly") or cfg["weekly"])


def tr_price(boss):
    cfg = tr_config()
    return int(cfg["modes"].get(str(tr_mode(boss)), {}).get("extraPrice", cfg["extraPrice"]))


def tr_new_boss(boss):
    return {"point": tr_weekly(boss), "recharge": 0, "best": 0, "bestTime": 0, "deckCount": 1, "decks": [],
            "rewards": [], "plays": 0, "last": 0, "cleared": 0}


def tr_state(state):
    """save.json "teamRelay" for this week: a new week refills the entries and starts the teams / best / rewards over"""
    s = state.setdefault("teamRelay", {})
    week = tr_week()[0]
    if s.get("week") != week or "bosses" not in s:
        old = s.get("bosses", {})
        s["week"], s["bosses"] = week, {}
        for k, b in old.items():
            s["bosses"][k] = {**tr_new_boss(int(k)), "decks": b.get("decks", [])}   # the saved teams stay, the rest starts over
        s.pop("current", None)
    for boss in tr_bosses():       # a boss new to an old save starts with a fresh state
        if str(boss) not in s["bosses"]:
            s["bosses"][str(boss)] = tr_new_boss(boss)
    return s


def tr_row(table, key, index):
    return next((r for r in table_rows(table) if r.get(key) == index), {})


def tr_dungeon(s, boss):
    """a TeamRelayDungeon entry (Point = entries left, Recharge = extra entries bought)"""
    b = s["bosses"][str(boss)]
    _, start, end = tr_week()
    season = tr_season(start)
    row = tr_row("TeamRelayTable", "teamRelayIndex", boss)
    best_group = row.get("bestRecordRewardGroup", 0)
    best_rows = {r["teamRelayRewardIndex"] for r in table_rows("TeamRelayRewardTable")
                 if best_group and r.get("teamRelayRewardGroup") == best_group}
    return apidefaults.default(
        "TeamRelayDungeon", TeamRelayIndex=boss, Point=b["point"], Recharge=b["recharge"], BestRecord=b["best"],
        BestRewardIndex=",".join(str(i) for i in b["rewards"] if i in best_rows), DeckCount=b["deckCount"],
        StageBuffIndexList=str(row.get("stageBuffIndexArray") or ""),
        Season=season, beforeSeason=season - 1, BestRecordTime=tr_secs(b["bestTime"]), BossHP=TR_BOSS_HP, PlayCount=b["plays"],
        BattleResult=b["cleared"], seasonStartTime=start, seasonEndTime=end, LastPlayScore=b["last"],
        clearResult=b["cleared"])


def tr_secs(t):
    """TeamRelayDungeon.BestRecordTime and TeamRelayMyRankInfoWebData.time are Int32 in the client: unix SECONDS
    (the first build stored ms, which broke the dungeonEnd parse; old saves are converted here)"""
    return int(t // 1000 if t > 2_000_000_000 else t)


def tr_ranking(b):
    """our own place on the (otherwise empty) board: first once there is a score"""
    return {"rank": 1 if b["best"] else 0, "rankRate": 0, "score": b["best"], "time": tr_secs(b["bestTime"])}


def tr_decks(b):
    keys = apidefaults.default("TeamRelayCharacter").keys()
    return [apidefaults.default("TeamRelayCharacter", **{k: v for k, v in d.items() if k in keys}) for d in b["decks"]]


def tr_schedules():
    """one always-open dungeon schedule per boss; without them the boss list stays empty (see above)"""
    return [apidefaults.default("OperateSchedule", Version=1, Category=DUNGEON_CATEGORY, SubCategory=TEAM_RELAY_DUNGEON,
                                Index=i, Detail=apidefaults.default("OperateScheduleData", SubGroup=[i],
                                                                    OffOnSched=ALWAYS_OPEN))
            for i in tr_bosses()]


def tr_boss_of(req):
    boss = int(req.get("TeamRelayIndex") or req.get("teamRelayIndex") or 0)
    return boss if boss in tr_bosses() else 0


@api("relayDungeon/dungeonInfoList")
def relay_dungeon_info_list(req):
    mode = int(req.get("ModeIndex") or 501)
    with _lock:
        state = load_state()
        s = tr_state(state)
        save_state(state)
    bosses = [b for b in tr_bosses() if tr_mode(b) == mode]
    return ok(ServerUtcTime=now_ms(), TeamRelayDungeonInfoList=[tr_dungeon(s, b) for b in bosses], RankingRewardList=[])


@api("relayDungeon/dungeonInfo")
def relay_dungeon_info(req):
    boss = tr_boss_of(req)
    if not boss:
        return sq_fail("no such boss")
    with _lock:
        state = load_state()
        s = tr_state(state)
        save_state(state)
    b = s["bosses"][str(boss)]
    return ok(ServerUtcTime=now_ms(), DungeonInfo=tr_dungeon(s, boss), TeamRelayTeamList=tr_decks(b),
              myRanking=tr_ranking(b))


@api("relayDungeon/teamDeckUpdate")
def relay_team_deck_update(req):
    """keep the boss's teams (TeamRelayCharacter per DeckNo); the Ready screen asks for them again in dungeonInfo"""
    boss = tr_boss_of(req)
    if not boss:
        return sq_fail("no such boss")
    with _lock:
        state = load_state()
        s = tr_state(state)
        s["bosses"][str(boss)]["decks"] = [d for d in req.get("TeamRelayTeamList") or [] if isinstance(d, dict)]
        save_state(state)
    return ok()


@api("relayDungeon/dungeonStart")
def relay_dungeon_start(req):
    """spend an entry (Point - 1) and remember the run; PlayToken comes back in dungeonEnd"""
    boss = tr_boss_of(req)
    if not boss:
        return sq_fail("no such boss")
    with _lock:
        state = load_state()
        s = tr_state(state)
        b = s["bosses"][str(boss)]
        if b["point"] <= 0:
            return sq_fail("no entries left")
        b["point"] -= 1
        b["plays"] += 1
        if req.get("TeamRelayTeamList"):
            b["decks"] = [d for d in req["TeamRelayTeamList"] if isinstance(d, dict)]
        token = now_ms()
        s["current"] = {"boss": boss, "token": token}
        save_state(state)
    return ok(PlayToken=token, BossHP=TR_BOSS_HP, AccountMoney=money(state))


def tr_pay(state, b, group, damage, repeat=False):
    """pay TeamRelayRewardTable rows of `group` -> (RewardContents to show, item ids, fighter rewards).
    repeat=False (best-record group): every threshold reached, each once a week (b["rewards"]).
    repeat=True (play group, the client's "Cumulative Record Reward"): every threshold reached, paid again every run
    (UIUnit_TeamRelayDamage.RewardInfo adds each passed row's reward to the in-battle counter: the giants' R Coins)."""
    contents, item_ids, fighters = [], [], []
    rows = sorted((r for r in table_rows("TeamRelayRewardTable") if group and r.get("teamRelayRewardGroup") == group
                   and damage >= r.get("conditionTotalDamage", 0)), key=lambda r: r.get("conditionTotalDamage", 0))
    for r in rows:
        i = r.get("teamRelayRewardIndex")
        if not repeat:
            if i in b["rewards"]:
                continue
            b["rewards"].append(i)
        got = give_rewards(state, r.get("rewardGroup", 0))
        contents += got[0]
        item_ids += got[1]
        fighters += got[2]
    return contents, item_ids, fighters


@api("relayDungeon/dungeonEnd")
def relay_dungeon_end(req):
    boss = tr_boss_of(req)
    damage, result = max(0, int(req.get("TotalDamage") or 0)), int(req.get("BattleResult") or 0)
    with _lock:
        state = load_state()
        s = tr_state(state)
        cur = s.get("current") or {}
        token = int(req.get("PlayToken") or 0)
        if not boss or cur.get("boss") != boss or (token and cur.get("token") and token != cur["token"]):
            return sq_fail("no run in progress")
        s.pop("current", None)
        b = s["bosses"][str(boss)]
        if result == TR_QUIT:     # quitting before the time runs out does not count the attempt: refund the entry
            b["point"] += 1
            b["plays"] = max(0, b["plays"] - 1)
            save_state(state)
            return ok(DungeonInfo=tr_dungeon(s, boss), AccountMoney=money(state), OldRanking=tr_ranking(b),
                      NewRanking=tr_ranking(b))
        old = tr_ranking(b)
        if damage > b["best"]:
            b["best"], b["bestTime"] = damage, now_ms() // 1000
        b["last"] = damage
        cleared = result == WIN
        b["cleared"] = 1 if cleared or b["cleared"] else 0
        if not cleared:
            b["deckCount"] = min(tr_config()["maxTeams"], b["deckCount"] + 1)
        row = tr_row("TeamRelayTable", "teamRelayIndex", boss)
        contents, item_ids, fighters = tr_pay(state, b, row.get("playRewardGroup", 0), damage, repeat=True)
        more = tr_pay(state, b, row.get("bestRecordRewardGroup", 0), b["best"])
        contents, fighters = contents + more[0], fighters + more[2]
        # the amounts gained, not the totals (Parse_QuestEventEnd adds each entry's Qty to the inventory); the result
        # screen lists GlobalDropRewardList (display only, as the Soul Quest)
        gained = [{"ItemIndex": c["ContentsIndex"], "Qty": c["ContentsCount"], "Lock": 0, "UpdateTime": now_ms()}
                  for c in contents if c["GoodsType"] == ITEM_GOODS]
        # GOLD on the RESULT "Play Reward" panel is not read from the lists: UIPage_StoryResultReward.CalculateGold
        # shows (AccountMoney.Gold now - the Gold before the last TakeAccountMoney) as a gold cell. A test account's
        # wallet is pinned to UNLIMITED_MONEY (regen_ap), so that delta was 0 and no gold appeared (rubies come from
        # the list, so they did): add the paid gold on top for this reply, the next reply pins it back. Gold stays
        # out of the lists so it isn't shown twice.
        gold = sum(c["ContentsCount"] for c in contents if c["GoodsType"] == GOLD_GOODS)
        shown = [c for c in contents if c["GoodsType"] != GOLD_GOODS]
        save_state(state)
    wallet = money(state)
    if state.get("unlimited") and gold:
        wallet["Gold"] = int(wallet["Gold"]) + gold
    return ok(DungeonInfo=tr_dungeon(s, boss), AccountMoney=wallet, RewardItemList=gained,
              RewardCharacterList=fighters, GlobalDropRewardList=shown, OldRanking=old, NewRanking=tr_ranking(b))


@api("relayDungeon/dungeonRecharge")
def relay_dungeon_recharge(req):
    """buy one more entry: the mode's extra price in rubies (free for a test player), Recharge + 1, Point + 1"""
    boss = tr_boss_of(req)
    cfg = tr_config()
    if not boss:
        return sq_fail("no such boss")
    with _lock:
        state = load_state()
        s = tr_state(state)
        b = s["bosses"][str(boss)]
        wallet = regen_ap(state)
        if b["recharge"] >= cfg["modes"].get(str(tr_mode(boss)), {}).get("extraMax", cfg.get("extraMax", 1 << 30)):
            return sq_fail("no extra entries left")
        if not state.get("unlimited"):
            price = tr_price(boss)
            if int(wallet.get("Cash", 0)) < price:
                return sq_fail("not enough rubies")
            wallet["Cash"] = int(wallet["Cash"]) - price
        b["recharge"] += 1
        b["point"] += 1
        save_state(state)
    return ok(Recharge=b["recharge"], Point=b["point"], AccountMoney=money(state))


@api("relayDungeon/dungeonMopup")
def relay_dungeon_mopup(req):
    """AUTO-CLEAR is not offered (no mop-up cost row): nothing is spent or paid, the entry is echoed"""
    boss = tr_boss_of(req)
    if not boss:
        return sq_fail("no such boss")
    with _lock:
        state = load_state()
        s = tr_state(state)
        save_state(state)
    return ok(DungeonInfo=tr_dungeon(s, boss), AccountMoney=money(state))


@api("relayDungeon/rankingInfoList")
def relay_ranking_info_list(req):
    """no other players offline: an empty board for the current week"""
    _, start, end = tr_week()
    season = tr_season(start)
    return ok(TeamRelayRankingSeason=apidefaults.default("TeamRelayRankingSeason", Season=season, SeasonDisplay=season,
                                                         SeasonStartDate=start, SeasonEndDate=end),
              RankingUserList=[])


@api("relayDungeon/rankingInfoDetail")
def relay_ranking_info_detail(req):
    """no other players offline; the path has no mapped response class, so send the detail response's defaults"""
    return ok(**{k: v for k, v in apidefaults.default("TeamRelayRankingDetailResponse").items()
                 if k not in ("ResultCode", "ResultMessage")})


API_MAP = json.load(open(os.path.join(HERE, "api_map.json"), encoding="utf-8"))
_ALIAS = {"player": ["Account", "Player"]}


def response_class(name):
    """Response class for an API path: from api_map.json (tools/api_map.py), else by naming convention."""
    e = API_MAP.get(name)
    if e and e.get("response"):
        return e["response"]
    group, api_name = (name.split("/", 1) + [""])[:2]
    a = api_name[:1].upper() + api_name[1:]
    for g in _ALIAS.get(group, [group[:1].upper() + group[1:]]):
        for c in (g + a + "Response", a + "Response"):
            if c in apidefaults.CLASSES:
                return c
    return None


def handle(name, req_json):
    """-> (response dict, handled?). Every reply starts as a fully defaulted object of the API's response class
    (no null fields for the client's Parse_* code to trip over); handlers override what they know."""
    cls = response_class(name)
    out = apidefaults.default(cls) if cls else {}
    out.update({"ResultCode": 0, "ResultMessage": ""})
    fn = APIS.get(name)
    got = fn(req_json) if fn is not None else {}
    out.update(got)
    # Replies such as player/renew, shop/shopGoodsQtyList and questEvent/questEventList set the client's clock
    # (GameDefine.UpdateServerTime, unix ms): a defaulted 0 puts it at 1970 and closes every scheduled event.
    for key in ("ServerUtcTime", "ServerTime", "serverUtcTime"):
        if key in out and key not in got:
            out[key] = now_ms()
    # The client replaces its money with any AccountMoney it receives (129 replies carry one, e.g. player/poll):
    # a defaulted all-zero one would empty the wallet, so fill it from the save unless the handler set it.
    if isinstance(out.get("AccountMoney"), dict) and "AccountMoney" not in got:
        state = load_state()
        if state is not None:
            out["AccountMoney"] = money(state)
    return out, fn is not None, cls


# A5 phase 1 (2026-11-09; recon/a5_process.md): feature modules register their own @api handlers
import ext_craft       # noqa: E402  CRAFT: Prime Memory from 1,000 shards
import ext_memory      # noqa: E402  memory COMBINE
import ext_dispatch    # noqa: E402  DISPATCH
import ext_eventbook   # noqa: E402  fighter codex (EventBook)
import ext_uecore    # noqa: E402  UE (Ultimate) core board, UE / PUE skills (2026-11-09)
import ext_cards     # noqa: E402  battle card level up / skill up / transcend / combine / sell / lock (2026-11-09)
import ext_backalley  # noqa: E402  Back Alley Mop-up Operation (QuestEvent 3401, card materials / card drops)
import ext_imprint   # noqa: E402  imprint stone enhancing (hammers), like / sell / disassemble
import ext_affinity  # noqa: E402  affinity gifts (affection/giveGift, level rewards, daily friendship points)
import ext_powerdungeons  # noqa: E402  Core Dungeon 3501 core drops, Awaken EXP dungeon 3601 schedule
import ext_plugins   # noqa: E402  UE/EX plugins (equipment/*, character/equipmentEquipUpdate)
import ext_pluginplant  # noqa: E402  Plugin Plant (equipmentDungeon/*: 5 colour plants, tier runs, plugin drops)
import ext_strikers  # noqa: E402  striker link gold / EXP payout on stage ends
import ext_corecost  # noqa: E402  core board spots cost cores (+ one-time core stock)
import ext_phantom   # noqa: E402  Tower of Illusion (QuestEvent 107, questEvent/phantomTower*)
import ext_sura      # noqa: E402  Sura Dungeon (QuestEvent 10801, suraDungeon/*)
import ext_prove     # noqa: E402  Prove / Dungeon of Trials (QuestEvent 10901, proveDungeon/*)
import ext_timeattack  # noqa: E402  Time Attack (challenge/*, ChallengeScheduleTable)
import ext_buffselect  # noqa: E402  Buff Select Dungeon (QuestEvent 8101, questEvent/buffDungeon*)
