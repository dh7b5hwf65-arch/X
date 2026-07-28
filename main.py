# -*- coding: utf-8 -*-
"""
Maç Sunma Botu
--------------
discord.py ile yazılmış canlı kadro + maç simülasyon botu.

Kurulum:
  pip install -r requirements.txt
  TOKEN değişkenini aşağıda doldur (ya da DISCORD_TOKEN ortam değişkenini ayarla)
  python main.py
"""

import os
import json
import random
import typing
import asyncio

import discord
from discord.ext import commands

# ============================================================
#  TOKEN -> Buraya kendi bot tokenini yaz
# ============================================================
TOKEN = os.getenv("DISCORD_TOKEN") or "BURAYA_BOT_TOKENINI_YAZ"

PREFIXES = ["!", "."]

# ============================================================
#  SABİTLER
# ============================================================

POS_NAMES = {
    "KLC": "Kaleci",
    "STP": "Stoper",
    "SGB": "Sağ Bek",
    "SLB": "Sol Bek",
    "DOS": "Defansif Orta Saha",
    "OS": "Orta Saha",
    "OOS": "Ofansif Orta Saha",
    "SGK": "Sağ Kanat",
    "SLK": "Sol Kanat",
    "SNT": "Santrafor",
}

# 11 kişilik diziliş (kod bazlı). İki tane STP olduğu için index önemli.
FORMATION = ["KLC", "SLB", "STP", "STP", "SGB", "DOS", "OS", "OOS", "SLK", "SNT", "SGK"]

NPC_NAMES = [
    "Ali Y.", "Veli K.", "Hasan T.", "Emre S.", "Burak D.", "Kerem A.",
    "Onur B.", "Deniz F.", "Serkan M.", "Caner G.", "Fatih R.", "Barış C.",
    "Uğur P.", "Tolga N.", "Yusuf E.", "Cem K.",
]

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
CARDS_PATH = os.path.join(DATA_DIR, "cards.json")
STATS_PATH = os.path.join(DATA_DIR, "stats.json")

os.makedirs(DATA_DIR, exist_ok=True)


def _load(path):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}


def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


cards = _load(CARDS_PATH)   # { "user_id": {"name","value","flag","position"} }
stats = _load(STATS_PATH)   # { "user_id": {"gol":0,"asist":0,"kurtaris":0} }

# Aktif maçlar: kanal id -> session sözlüğü
matches = {}


def save_cards():
    _save(CARDS_PATH, cards)


def save_stats():
    _save(STATS_PATH, stats)


def normalize_pos(raw: str) -> str:
    raw = raw.strip().upper()
    table = str.maketrans({"Ğ": "G", "İ": "I", "Ş": "S", "Ç": "C", "Ö": "O", "Ü": "U"})
    raw = raw.translate(table)
    return raw


def get_tier(value: int) -> str:
    if value <= 50:
        return "Kötü Topçu"
    elif value <= 99:
        return "Normal Topçu"
    elif value <= 199:
        return "İyi Topçu"
    elif value <= 249:
        return "Yıldız Topçu"
    else:
        return "Süperstar Topçu"


def parse_value(raw: str) -> int:
    raw = raw.upper().replace("M", "").replace(" ", "").replace(",", ".")
    return int(float(raw))


def make_npc(code: str) -> dict:
    return {
        "name": random.choice(NPC_NAMES),
        "value": random.randint(0, 50),
        "flag": "🏳️",
        "position": code,
        "user_id": None,
        "oop": False,
        "npc": True,
    }


def eff_value(entry: dict) -> float:
    val = entry.get("value", 0)
    if entry.get("oop"):
        val = val * 0.6
    return max(val, 1)


def get_team_cards(role: discord.Role):
    """Bir rolün üyelerinden kartı olanları döndürür -> [(member, card_dict)]"""
    out = []
    for member in role.members:
        c = cards.get(str(member.id))
        if c:
            out.append((member, c))
    return out


def stat_add(entry: dict, key: str, amount: int = 1):
    uid = entry.get("user_id")
    if not uid:
        return  # NPC ise stat tutulmaz
    s = stats.setdefault(str(uid), {"gol": 0, "asist": 0, "kurtaris": 0})
    s[key] = s.get(key, 0) + amount


def pick_weighted(pool, exclude_idx=None):
    """pool: list of (idx, entry). Rating'e göre ağırlıklı seçim."""
    candidates = [(i, e) for i, e in pool if i != exclude_idx]
    if not candidates:
        candidates = pool
    weights = [eff_value(e) + 1 for _, e in candidates]
    choice = random.choices(candidates, weights=weights, k=1)[0]
    return choice  # (idx, entry)


def get_gk(lineup: dict):
    for idx, code in enumerate(FORMATION):
        if code == "KLC" and idx in lineup:
            return lineup[idx]
    return make_npc("KLC")


# ============================================================
#  BOT KURULUMU
# ============================================================

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=PREFIXES, intents=intents, help_command=None)


@bot.event
async def on_ready():
    print(f"Giriş yapıldı: {bot.user} ({bot.user.id})")


# ============================================================
#  KART (OYUNCU) KOMUTLARI
# ============================================================

@bot.command(name="kart")
async def kart_cmd(ctx, member: typing.Optional[discord.Member] = None, *, bilgi: str = None):
    """!kart @kullanıcı İsim | Değer(M) | Bayrak | Mevki"""
    if bilgi is None:
        await ctx.send(
            "Kullanım: `!kart @kullanıcı İsim Soyisim | 120M | 🇹🇷 | SNT`\n"
            "Geçerli mevkiler: " + ", ".join(POS_NAMES.keys())
        )
        return

    target = member or ctx.author
    if target != ctx.author and not ctx.author.guild_permissions.administrator:
        await ctx.send("Sadece kendi kartını oluşturabilirsin (ya da bir yönetici başkasına kart açabilir).")
        return

    parts = [p.strip() for p in bilgi.split("|")]
    if len(parts) != 4:
        await ctx.send("Format hatalı! Örnek: `!kart @kullanıcı İsim | 120M | 🇹🇷 | SNT`")
        return

    name, value_raw, flag, pos_raw = parts
    try:
        value = parse_value(value_raw)
    except ValueError:
        await ctx.send("Değer sayısal olmalı. Örnek: `120M` veya `120`.")
        return

    pos = normalize_pos(pos_raw)
    if pos not in POS_NAMES:
        await ctx.send("Geçersiz mevki! Geçerli mevkiler: " + ", ".join(POS_NAMES.keys()))
        return

    cards[str(target.id)] = {"name": name, "value": value, "flag": flag, "position": pos}
    save_cards()

    embed = discord.Embed(title="✅ Kart Oluşturuldu / Güncellendi", color=discord.Color.green())
    embed.add_field(name="Oyuncu", value=f"{name} {flag}", inline=True)
    embed.add_field(name="Değer", value=f"{value}M ({get_tier(value)})", inline=True)
    embed.add_field(name="Mevki", value=f"{pos} - {POS_NAMES[pos]}", inline=True)
    embed.set_footer(text=f"Sahibi: {target.display_name}")
    await ctx.send(embed=embed)


@bot.command(name="kartgor")
async def kartgor_cmd(ctx, member: typing.Optional[discord.Member] = None):
    target = member or ctx.author
    c = cards.get(str(target.id))
    if not c:
        await ctx.send(f"{target.display_name} için kayıtlı bir kart bulunamadı. `!kart` ile oluşturabilir.")
        return
    embed = discord.Embed(title=f"{c['flag']} {c['name']}", color=discord.Color.blurple())
    embed.add_field(name="Değer", value=f"{c['value']}M", inline=True)
    embed.add_field(name="Seviye", value=get_tier(c["value"]), inline=True)
    embed.add_field(name="Mevki", value=f"{c['position']} - {POS_NAMES.get(c['position'], c['position'])}", inline=True)
    embed.set_footer(text=f"Sahibi: {target.display_name}")
    await ctx.send(embed=embed)


@bot.command(name="kadrolar")
async def kadrolar_cmd(ctx, role: discord.Role):
    team = get_team_cards(role)
    if not team:
        await ctx.send(f"**{role.name}** rolünde kayıtlı kart bulunan kimse yok.")
        return
    embed = discord.Embed(title=f"📋 {role.name} - Kayıtlı Kartlar", color=role.color)
    for member, c in team:
        embed.add_field(
            name=f"{c['flag']} {c['name']} ({member.display_name})",
            value=f"{c['value']}M - {get_tier(c['value'])} - {c['position']}",
            inline=False,
        )
    await ctx.send(embed=embed)


# ============================================================
#  CANLI KADRO PANELİ (UI)
# ============================================================

class SlotSelect(discord.ui.Select):
    def __init__(self, session, team_key, idx, code):
        team_cards = session[f"{team_key}_cards"]
        matching = [(m, c) for m, c in team_cards if c["position"] == code]
        others = [(m, c) for m, c in team_cards if c["position"] != code]

        options = []
        for m, c in matching[:12]:
            options.append(discord.SelectOption(
                label=f"{c['name']} ({get_tier(c['value'])[:10]})",
                description=f"{c['value']}M - {c['flag']} - Uygun mevki",
                value=str(m.id),
            ))
        for m, c in others[:10]:
            options.append(discord.SelectOption(
                label=f"⚠️ {c['name']} (OOP)",
                description=f"{c['value']}M - Asıl mevki: {c['position']} (performans düşer)",
                value=f"oop:{m.id}",
            ))
        options.append(discord.SelectOption(label="🤖 NPC (Otomatik Oyuncu)", value="npc"))

        super().__init__(
            placeholder=f"{POS_NAMES.get(code, code)} ({code}) seç...",
            options=options[:25],
            min_values=1, max_values=1,
        )
        self.session = session
        self.team_key = team_key
        self.idx = idx
        self.code = code

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        lineup = self.session[f"{self.team_key}_lineup"]
        if val == "npc":
            lineup[self.idx] = make_npc(self.code)
        elif val.startswith("oop:"):
            uid = val.split(":", 1)[1]
            c = cards[uid]
            lineup[self.idx] = {**c, "user_id": uid, "oop": True, "npc": False}
        else:
            uid = val
            c = cards[uid]
            lineup[self.idx] = {**c, "user_id": uid, "oop": False, "npc": False}
        await interaction.response.send_message(
            f"**{POS_NAMES.get(self.code, self.code)}** için **{lineup[self.idx]['name']}** seçildi.",
            ephemeral=True,
        )


class PageButton(discord.ui.Button):
    def __init__(self, session, team_key, target_page, label):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.session = session
        self.team_key = team_key
        self.target_page = target_page

    async def callback(self, interaction: discord.Interaction):
        view = LineupView(self.session, self.team_key, self.target_page)
        embed = build_lineup_embed(self.session, self.team_key, self.target_page)
        await interaction.response.edit_message(embed=embed, view=view)


class ConfirmLineupButton(discord.ui.Button):
    def __init__(self, session, team_key):
        super().__init__(label="✅ Kadroyu Onayla", style=discord.ButtonStyle.success)
        self.session = session
        self.team_key = team_key

    async def callback(self, interaction: discord.Interaction):
        lineup = self.session[f"{self.team_key}_lineup"]
        for idx, code in enumerate(FORMATION):
            if idx not in lineup:
                lineup[idx] = make_npc(code)

        embed = discord.Embed(
            title=f"✅ {self.session[f'{self.team_key}_name']} Kadrosu Onaylandı",
            color=discord.Color.green(),
        )
        for idx, code in enumerate(FORMATION):
            p = lineup[idx]
            tag = " (NPC)" if p.get("npc") else (" (OOP)" if p.get("oop") else "")
            embed.add_field(
                name=f"{code} - {POS_NAMES.get(code, code)}",
                value=f"{p['flag']} {p['name']}{tag} - {p['value']}M",
                inline=False,
            )
        await interaction.response.edit_message(embed=embed, view=None)

        if self.team_key == "team1":
            self.session["stage"] = "team2_lineup"
            next_view = LineupView(self.session, "team2", 0)
            next_embed = build_lineup_embed(self.session, "team2", 0)
            await interaction.followup.send(embed=next_embed, view=next_view)
        else:
            self.session["stage"] = "setpieces_team1"
            next_view = SetPieceView(self.session, "team1")
            next_embed = build_setpiece_embed(self.session, "team1")
            await interaction.followup.send(embed=next_embed, view=next_view)


class LineupView(discord.ui.View):
    PAGE_SIZE = 4

    def __init__(self, session, team_key, page):
        super().__init__(timeout=600)
        self.session = session
        self.team_key = team_key
        self.page = page

        start = page * self.PAGE_SIZE
        chunk = list(enumerate(FORMATION))[start:start + self.PAGE_SIZE]
        for idx, code in chunk:
            self.add_item(SlotSelect(session, team_key, idx, code))

        nav_row = []
        if page > 0:
            self.add_item(PageButton(session, team_key, page - 1, "◀ Geri"))
        if start + self.PAGE_SIZE < len(FORMATION):
            self.add_item(PageButton(session, team_key, page + 1, "İleri ▶"))
        else:
            self.add_item(ConfirmLineupButton(session, team_key))


def build_lineup_embed(session, team_key, page):
    team_name = session[f"{team_key}_name"]
    start = page * LineupView.PAGE_SIZE
    chunk = list(enumerate(FORMATION))[start:start + LineupView.PAGE_SIZE]
    embed = discord.Embed(
        title=f"🧩 Canlı Kadro Paneli - {team_name}",
        description=f"Sayfa {page + 1} - Aşağıdaki mevkiler için oyuncu seç.",
        color=discord.Color.orange(),
    )
    for idx, code in chunk:
        embed.add_field(name=f"{code} - {POS_NAMES.get(code, code)}", value="Seçim bekleniyor...", inline=False)
    return embed


# --- Duran toplar ---

SETPIECE_KEYS = [
    ("korner", "🚩 Korner Atan"),
    ("frikik_uzak", "🦶 Uzak Frikik"),
    ("frikik_yakin", "🦶 Yakın Frikik"),
    ("penalti", "🥅 Penaltı Kullanan"),
]


class SetPieceSelect(discord.ui.Select):
    def __init__(self, session, team_key, key, label):
        lineup = session[f"{team_key}_lineup"]
        options = []
        for idx, code in enumerate(FORMATION):
            p = lineup[idx]
            options.append(discord.SelectOption(
                label=f"{p['name']} ({code})",
                description=f"{p['value']}M - {get_tier(p['value'])[:12]}",
                value=str(idx),
            ))
        super().__init__(placeholder=label, options=options[:25], min_values=1, max_values=1)
        self.session = session
        self.team_key = team_key
        self.key = key

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        self.session.setdefault(f"{self.team_key}_setpieces", {})[self.key] = idx
        p = self.session[f"{self.team_key}_lineup"][idx]
        await interaction.response.send_message(f"**{self.key}** için **{p['name']}** seçildi.", ephemeral=True)


class ConfirmSetPieceButton(discord.ui.Button):
    def __init__(self, session, team_key):
        super().__init__(label="✅ Onayla", style=discord.ButtonStyle.success)
        self.session = session
        self.team_key = team_key

    async def callback(self, interaction: discord.Interaction):
        sp = self.session.setdefault(f"{self.team_key}_setpieces", {})
        lineup = self.session[f"{self.team_key}_lineup"]
        for key, _ in SETPIECE_KEYS:
            if key not in sp:
                sp[key] = 0  # varsayılan olarak ilk oyuncu (kaleci hariç genelde 0 = KLC ama basit tutuyoruz)

        embed = discord.Embed(title=f"✅ {self.session[f'{self.team_key}_name']} Duran Toplar Ayarlandı", color=discord.Color.green())
        for key, label in SETPIECE_KEYS:
            p = lineup[sp[key]]
            embed.add_field(name=label, value=f"{p['flag']} {p['name']}", inline=True)
        await interaction.response.edit_message(embed=embed, view=None)

        if self.team_key == "team1":
            self.session["stage"] = "setpieces_team2"
            next_view = SetPieceView(self.session, "team2")
            next_embed = build_setpiece_embed(self.session, "team2")
            await interaction.followup.send(embed=next_embed, view=next_view)
        else:
            self.session["stage"] = "ready"
            await interaction.followup.send(
                "🏟️ **Kadrolar ve duran toplar hazır!** Maçı başlatmak için `!baslat` yaz."
            )


class SetPieceView(discord.ui.View):
    def __init__(self, session, team_key):
        super().__init__(timeout=600)
        for key, label in SETPIECE_KEYS:
            self.add_item(SetPieceSelect(session, team_key, key, label))
        self.add_item(ConfirmSetPieceButton(session, team_key))


def build_setpiece_embed(session, team_key):
    return discord.Embed(
        title=f"🎯 Duran Top Kullanıcıları - {session[f'{team_key}_name']}",
        description="Korner, frikik (uzak/yakın) ve penaltı kullanıcılarını seç.",
        color=discord.Color.gold(),
    )


# ============================================================
#  !mac KOMUTU
# ============================================================

@bot.command(name="mac")
async def mac_cmd(ctx, rol1: discord.Role, rol2: discord.Role):
    team1_cards = get_team_cards(rol1)
    team2_cards = get_team_cards(rol2)

    session = {
        "team1_name": rol1.name,
        "team2_name": rol2.name,
        "team1_cards": team1_cards,
        "team2_cards": team2_cards,
        "team1_lineup": {},
        "team2_lineup": {},
        "team1_setpieces": {},
        "team2_setpieces": {},
        "stage": "team1_lineup",
        "score": [0, 0],
        "channel_id": ctx.channel.id,
    }
    matches[ctx.channel.id] = session

    await ctx.send(
        f"⚽ **MAÇ BAŞLIYOR:** {rol1.mention} 🆚 {rol2.mention}\n"
        f"Önce **{rol1.name}** kadrosunu kuralım."
    )
    view = LineupView(session, "team1", 0)
    embed = build_lineup_embed(session, "team1", 0)
    await ctx.send(embed=embed, view=view)


# ============================================================
#  MAÇ SİMÜLASYONU
# ============================================================

EVENT_TITLES = {
    "pas": "🔁 PAS",
    "orta": "🚀 ORTA",
    "sut": "🎯 ŞUT DENEMESİ",
    "korner": "🚩 KORNER",
    "frikik": "🦶 SERBEST VURUŞ",
    "penalti": "🥅 PENALTI",
    "gol": "⚽ GOOOL!",
    "kurtaris": "🧤 KURTARIŞ",
    "kacti": "❌ AUT / KAÇTI",
}


def action_embed(minute, team_name, entry, action, distance):
    title = EVENT_TITLES.get(action, action.upper())
    embed = discord.Embed(title=f"{title} - {minute}'", color=discord.Color.blue())
    embed.add_field(name="Takım", value=team_name, inline=True)
    embed.add_field(name="Oyuncu", value=f"{entry['flag']} {entry['name']}", inline=True)
    embed.add_field(name="Mesafe", value=f"{distance} metre", inline=True)
    return embed


def goal_embed(minute, team_name, scorer, assister, distance):
    embed = discord.Embed(title=f"⚽ GOOOL! - {minute}'", color=discord.Color.gold())
    embed.add_field(name="Takım", value=team_name, inline=False)
    embed.add_field(name="Golcü", value=f"{scorer['flag']} {scorer['name']} ({distance}m)", inline=True)
    if assister:
        embed.add_field(name="Asist", value=f"{assister['flag']} {assister['name']}", inline=True)
    return embed


def result_embed(minute, team_name, entry, gk_entry, distance, action, saved):
    title = "🧤 KURTARIŞ!" if saved else "❌ KAÇTI / AUT"
    embed = discord.Embed(title=f"{title} - {minute}'", color=discord.Color.dark_grey())
    embed.add_field(name="Takım", value=team_name, inline=True)
    embed.add_field(name=f"{EVENT_TITLES.get(action)} Kullanan", value=f"{entry['flag']} {entry['name']}", inline=True)
    embed.add_field(name="Mesafe", value=f"{distance} metre", inline=True)
    if saved:
        embed.add_field(name="Kaleci", value=f"{gk_entry['flag']} {gk_entry['name']}", inline=True)
    return embed


def get_setpiece_player(session, team_key, action):
    sp = session.get(f"{team_key}_setpieces", {})
    lineup = session[f"{team_key}_lineup"]
    key_map = {"korner": "korner", "frikik": "frikik_uzak", "penalti": "penalti"}
    key = key_map.get(action)
    if key and key in sp:
        return sp[key], lineup[sp[key]]
    idx, entry = pick_weighted(list(lineup.items()))
    return idx, entry


async def simulate_match(ctx, session):
    score = [0, 0]
    minute = 0
    events_count = random.randint(14, 18)
    step = max(90 // events_count, 3)

    await ctx.send("🏟️ **MAÇ BAŞLADI!** Başlangıç düdüğü çaldı, oyun içeride.")

    for _ in range(events_count):
        minute = min(minute + step + random.randint(-1, 3), 90)
        attacking = random.choice([0, 1])
        team_key = "team1" if attacking == 0 else "team2"
        def_key = "team2" if attacking == 0 else "team1"
        team_name = session[f"{team_key}_name"]
        lineup = session[f"{team_key}_lineup"]
        def_lineup = session[f"{def_key}_lineup"]

        action = random.choices(
            ["pas", "orta", "sut", "korner", "frikik", "penalti"],
            weights=[26, 20, 26, 12, 11, 5],
            k=1,
        )[0]

        if action in ("sut", "korner", "frikik", "penalti"):
            if action in ("korner", "frikik", "penalti"):
                shooter_idx, shooter = get_setpiece_player(session, team_key, action)
            else:
                shooter_idx, shooter = pick_weighted(
                    [(i, e) for i, e in lineup.items() if e["position"] != "KLC"]
                )

            gk = get_gk(def_lineup)
            distance = 11 if action == "penalti" else random.randint(6, 35)

            base = {"sut": 0.22, "korner": 0.12, "frikik": 0.18, "penalti": 0.72}[action]
            chance = base + (eff_value(shooter) - 100) / 700 - (eff_value(gk) - 100) / 900
            chance = min(max(chance, 0.03), 0.9)

            is_goal = random.random() < chance
            if is_goal:
                score[attacking] += 1
                assister = None
                if action == "sut" and random.random() < 0.55:
                    a_idx, assister = pick_weighted(
                        [(i, e) for i, e in lineup.items() if i != shooter_idx], exclude_idx=shooter_idx
                    )
                    stat_add(assister, "asist")
                stat_add(shooter, "gol")
                embed = goal_embed(minute, team_name, shooter, assister, distance)
            else:
                saved = random.random() < 0.55
                if saved:
                    stat_add(gk, "kurtaris")
                embed = result_embed(minute, team_name, shooter, gk, distance, action, saved)
        else:
            idx, player = pick_weighted(list(lineup.items()))
            distance = random.randint(5, 60) if action == "orta" else random.randint(2, 40)
            embed = action_embed(minute, team_name, player, action, distance)

        await ctx.send(embed=embed)
        await asyncio.sleep(1.5)

    session["score"] = score
    save_stats()

    winner = session["team1_name"] if score[0] > score[1] else (
        session["team2_name"] if score[1] > score[0] else "Berabere"
    )
    final = discord.Embed(
        title="🏁 MAÇ SONA ERDİ",
        description=f"**{session['team1_name']} {score[0]} - {score[1]} {session['team2_name']}**",
        color=discord.Color.purple(),
    )
    final.add_field(name="Sonuç", value=winner if winner == "Berabere" else f"Kazanan: {winner}")
    await ctx.send(embed=final)
    session["stage"] = "finished"


@bot.command(name="baslat")
async def baslat_cmd(ctx):
    session = matches.get(ctx.channel.id)
    if not session:
        await ctx.send("Bu kanalda kurulmuş bir maç yok. Önce `!mac @rol1 @rol2` kullan.")
        return
    if session["stage"] != "ready":
        await ctx.send("Kadrolar ve duran toplar henüz tamamlanmadı.")
        return
    await simulate_match(ctx, session)


# ============================================================
#  STAT KOMUTU: .s @kullanıcı
# ============================================================

@bot.command(name="s")
async def stat_cmd(ctx, member: typing.Optional[discord.Member] = None):
    target = member or ctx.author
    st = stats.get(str(target.id), {"gol": 0, "asist": 0, "kurtaris": 0})
    c = cards.get(str(target.id))

    embed = discord.Embed(title=f"📊 {target.display_name} İstatistikleri", color=discord.Color.teal())
    if c:
        embed.description = f"{c['flag']} {c['name']} - {c['position']} - {c['value']}M ({get_tier(c['value'])})"
    embed.add_field(name="⚽ Gol", value=st.get("gol", 0), inline=True)
    embed.add_field(name="🎯 Asist", value=st.get("asist", 0), inline=True)
    embed.add_field(name="🧤 Kurtarış", value=st.get("kurtaris", 0), inline=True)
    await ctx.send(embed=embed)


# ============================================================
#  YARDIM
# ============================================================

@bot.command(name="yardim")
async def yardim_cmd(ctx):
    embed = discord.Embed(title="📖 Komutlar", color=discord.Color.blurple())
    embed.add_field(
        name="!kart @kullanıcı İsim | Değer | Bayrak | Mevki",
        value="Kendi oyuncu kartını oluşturur/günceller.",
        inline=False,
    )
    embed.add_field(name="!kartgor [@kullanıcı]", value="Bir kartı gösterir.", inline=False)
    embed.add_field(name="!kadrolar @rol", value="Rolün kayıtlı oyuncularını listeler.", inline=False)
    embed.add_field(name="!mac @rol1 @rol2", value="Canlı kadro panelini açar.", inline=False)
    embed.add_field(name="!baslat", value="Kadrolar hazır olunca maçı başlatır.", inline=False)
    embed.add_field(name=".s @kullanıcı", value="Gol/asist/kurtarış istatistiklerini gösterir.", inline=False)
    embed.add_field(name="Mevki Kodları", value=", ".join(f"{k} ({v})" for k, v in POS_NAMES.items()), inline=False)
    await ctx.send(embed=embed)


if __name__ == "__main__":
    if TOKEN == "BURAYA_BOT_TOKENINI_YAZ":
        print("UYARI: main.py içindeki TOKEN değişkenini doldurmadan botu çalıştıramazsın.")
    bot.run(TOKEN)
