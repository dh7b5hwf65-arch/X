# -*- coding: utf-8 -*-
"""
MAÇ SUNMA BOTU
==============
Tek dosyalık discord.py botu.

Kurulum:
    pip install -U discord.py

Çalıştırma:
    TOKEN değişkenine kendi bot tokenini yaz (aşağıda BOT_TOKEN) ya da
    ortam değişkeni olarak DISCORD_BOT_TOKEN ver, sonra:
    python mac_botu.py

Gerekli intent'ler Discord Developer Portal'da açık olmalı:
    - SERVER MEMBERS INTENT
    - MESSAGE CONTENT INTENT

Botun sunucudaki rolü "Manage Nicknames" (Takma Adları Yönet) iznine sahip
olmalı ve hedef üyelerin rolünden yüksekte olmalı; aksi halde .dver/.dsil/
.dpoz/.dulke ile nickname otomatik güncellenemez.

Komutlar hem "." hem "!" öneki ile çalışır (ör: .dver / !dver, !mac / .mac).
"""

import os
import re
import json
import random
import asyncio
from datetime import datetime, timezone

import discord
from discord.ext import commands

# ----------------------------------------------------------------------------
# AYARLAR
# ----------------------------------------------------------------------------

BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "BURAYA_BOT_TOKENINI_YAZ")

DATA_FILE = "data.json"

# Takım rolleri (mesajdan alındı) -> {isim, emoji}
TEAM_INFO = {
    1522570889516945419: {"name": "Dortmund",  "emoji": "<:dortmund:1527776798513958983>"},
    1522570886207766559: {"name": "Barcelona", "emoji": "<:barcelona:1527776939182395634>"},
    1522570890661859398: {"name": "PSG",       "emoji": "<:PSG:1527777062562041930>"},
    1522570887990083584: {"name": "Bayern",    "emoji": "<:Bayern:1527777181755772949>"},
    1522570898308337714: {"name": "Arsenal",   "emoji": "<:arsenal:1527777372340752517>"},
    1522570885490278420: {"name": "Real Madrid","emoji": "<:real:1527777951289053277>"},
    1522570891777806437: {"name": "Marsilya",  "emoji": "<:marsilya:1527778265341755442>"},
    1522570894013366434: {"name": "United",    "emoji": "<:united:1527778391884042353>"},
    1522570892612342001: {"name": "City",      "emoji": "<:city:1527778582603104266>"},
    1522570896206856202: {"name": "Juventus",  "emoji": "<:juventus:1527778702727839926>"},
    1522570897318346964: {"name": "Chelsea",   "emoji": "<:chelsea:1527778840074518588>"},
    1522570894919204897: {"name": "Napoli",    "emoji": "<:napoli:1527778984614564052>"},
}

# 11 kişilik dizilişteki mevki slotları (formasyon 1-4-3-3 benzeri)
FORMATION_SLOTS = [
    ("KL",   "Kaleci"),
    ("SLB",  "Sol Bek"),
    ("STP1", "Stoper"),
    ("STP2", "Stoper"),
    ("SĞB",  "Sağ Bek"),
    ("DOS",  "Defansif Orta Saha"),
    ("OS",   "Orta Saha"),
    ("OOS",  "Ofansif Orta Saha"),
    ("SLK",  "Sol Kanat"),
    ("SNT",  "Santrfor"),
    ("SĞK",  "Sağ Kanat"),
]

# Slot -> gerçek mevki kodu (STP1/STP2 ikisi de STP sayılır)
def base_position(slot: str) -> str:
    if slot.startswith("STP"):
        return "STP"
    return slot

ALL_POSITIONS = ["KL", "SLB", "STP", "SĞB", "DOS", "OS", "OOS", "SLK", "SNT", "SĞK"]

STAT_TYPES = ["gol", "asist", "mudahale", "kurtarış"]
STAT_LABELS = {"gol": "⚽ Gol", "asist": "🅰️ Asist", "mudahale": "🛡️ Müdahale", "kurtarış": "🧤 Kurtarış"}

# ----------------------------------------------------------------------------
# VERİ KATMANI (basit json depolama)
# ----------------------------------------------------------------------------

def load_data():
    if not os.path.exists(DATA_FILE):
        return {"stats": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        try:
            d = json.load(f)
            d.setdefault("stats", {})
            return d
        except json.JSONDecodeError:
            return {"stats": {}}

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

DATA = load_data()

def get_stats(user_id: int):
    uid = str(user_id)
    if uid not in DATA["stats"]:
        DATA["stats"][uid] = {k: 0 for k in STAT_TYPES}
        save_data(DATA)
    return DATA["stats"][uid]

def add_stat(user_id: int, stat: str, amount: int = 1):
    st = get_stats(user_id)
    st[stat] = max(0, st.get(stat, 0) + amount)
    save_data(DATA)

# ----------------------------------------------------------------------------
# DEĞER KADEMESİ (0-49 kötü, 50-99 normal, 100-199 iyi, 200-249 star, 250+ süperstar)
# ----------------------------------------------------------------------------

def tier_info(value: int):
    if value < 50:
        return "Kötü", 0.65
    elif value < 100:
        return "Normal", 1.0
    elif value < 200:
        return "İyi", 1.3
    elif value < 250:
        return "Star", 1.6
    else:
        return "Süperstar", 2.0

def format_card(card: dict) -> str:
    return f"{card['name']} | {int(card['value'])}M | {card['country']} | {card['position']}"

# ----------------------------------------------------------------------------
# NICKNAME'DEN KART OKUMA
# Ayrı bir "kart" veritabanı yok — kullanıcının sunucu takma adı zaten
# "İsim | DeğerM | Ülke | Mevki" formatındaysa bot otomatik olarak bunu
# okur ve o kullanıcıyı kadro panelinde seçilebilir yapar.
# ----------------------------------------------------------------------------

NICK_PATTERN = re.compile(r"^(.*?)\s*\|\s*(\d+)\s*M?\s*\|\s*(\S+)\s*\|\s*([^\s|]+)\s*$", re.IGNORECASE)

def parse_card_from_text(text: str):
    if not text:
        return None
    m = NICK_PATTERN.match(text.strip())
    if not m:
        return None
    name, value, country, mevki = m.groups()
    mevki_up = mevki.upper()
    if mevki_up not in ALL_POSITIONS:
        return None
    return {"name": name.strip(), "value": int(value), "country": country, "position": mevki_up}

def get_member_card(member: discord.Member):
    """Kullanıcının mevcut takma adını okuyup format uyuyorsa kart olarak döndürür."""
    return parse_card_from_text(member.nick) or parse_card_from_text(member.name)

def build_nick(card: dict) -> str:
    nick = format_card(card)
    return nick[:32]  # discord nickname limiti

# ----------------------------------------------------------------------------
# BOT KURULUMU
# ----------------------------------------------------------------------------

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix=["!", "."], intents=intents, help_command=None)

# ----------------------------------------------------------------------------
# YARDIMCI: takım üyelerini bul (role sahip + nicki uygun formatta olanlar)
# ----------------------------------------------------------------------------

def team_members_with_cards(role: discord.Role):
    result = []
    for member in role.members:
        card = get_member_card(member)
        if card:
            result.append((member, card))
    return result

# ----------------------------------------------------------------------------
# MAÇ DURUMU
# ----------------------------------------------------------------------------

class TeamSide:
    def __init__(self, role: discord.Role):
        self.role = role
        self.name = TEAM_INFO.get(role.id, {}).get("name", role.name)
        self.emoji = TEAM_INFO.get(role.id, {}).get("emoji", "")
        self.lineup = {}          # slot -> {"member": Member|None, "card": dict}
        self.duties = {"kaptan": None, "korner": None, "frikik": None, "penaltı": None}
        self.score = 0

    def filled_slots(self):
        return [s for s, _ in FORMATION_SLOTS if s in self.lineup]

    def is_complete(self):
        return all(slot in self.lineup for slot, _ in FORMATION_SLOTS)

    def fill_npc_remaining(self):
        npc_names = ["Alex Doe", "João Silva", "Marko Novak", "Kwame Boateng", "Ivan Petrov",
                     "Lucas Moretti", "Sami Karim", "Erik Lund", "Diego Ramos", "Tom Hughes", "Noah Cohen"]
        for slot, _ in FORMATION_SLOTS:
            if slot not in self.lineup:
                value = random.randint(20, 90)
                card = {
                    "name": random.choice(npc_names) + f" (NPC)",
                    "value": value,
                    "country": "🏳️",
                    "position": base_position(slot),
                }
                self.lineup[slot] = {"member": None, "card": card}

    def all_players(self):
        return list(self.lineup.items())


class Match:
    def __init__(self, channel_id: int, team1: TeamSide, team2: TeamSide, starter_id: int):
        self.channel_id = channel_id
        self.team1 = team1
        self.team2 = team2
        self.starter_id = starter_id
        self.stage = "kadro1"  # kadro1 -> kadro2 -> gorev1 -> gorev2 -> hazir -> oynaniyor -> bitti


active_matches = {}  # channel_id -> Match

# ----------------------------------------------------------------------------
# UI: KADRO PANELİ
# ----------------------------------------------------------------------------

class PositionSelect(discord.ui.Select):
    def __init__(self, match: Match, team: TeamSide):
        self.match = match
        self.team = team
        options = []
        for slot, label in FORMATION_SLOTS:
            mark = "✅" if slot in team.lineup else "⬜"
            filled_name = team.lineup[slot]["card"]["name"] if slot in team.lineup else "boş"
            options.append(discord.SelectOption(
                label=f"{mark} {label} ({slot})",
                description=f"Şu an: {filled_name}"[:100],
                value=slot,
            ))
        super().__init__(placeholder="Bir mevki seç ve oyuncu ata...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.match.starter_id and self.team.role not in interaction.user.roles:
            await interaction.response.send_message("Bu kadroyu sen düzenleyemezsin.", ephemeral=True)
            return
        slot = self.values[0]
        view = PlayerPickView(self.match, self.team, slot)
        await interaction.response.edit_message(
            content=f"**{self.team.emoji} {self.team.name}** kadrosu — `{slot}` mevkisi için oyuncu seç:",
            embed=None, view=view,
        )


class LineupPanelView(discord.ui.View):
    def __init__(self, match: Match, team: TeamSide):
        super().__init__(timeout=600)
        self.match = match
        self.team = team
        self.add_item(PositionSelect(match, team))

    @discord.ui.button(label="Kadroyu Onayla", style=discord.ButtonStyle.green, row=1)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.team.fill_npc_remaining()
        await interaction.response.edit_message(
            content=f"**{self.team.emoji} {self.team.name}** kadrosu onaylandı.\n" + lineup_text(self.team),
            embed=None, view=None,
        )
        await advance_match_stage(interaction, self.match)

    @discord.ui.button(label="Otomatik Doldur (NPC)", style=discord.ButtonStyle.gray, row=1)
    async def auto_fill(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.team.fill_npc_remaining()
        view = LineupPanelView(self.match, self.team)
        await interaction.response.edit_message(
            content=f"**{self.team.emoji} {self.team.name}** — kalan mevkiler NPC ile dolduruldu.\n" + lineup_text(self.team),
            embed=None, view=view,
        )


class PlayerPickView(discord.ui.View):
    def __init__(self, match: Match, team: TeamSide, slot: str):
        super().__init__(timeout=300)
        self.match = match
        self.team = team
        self.slot = slot

        members_cards = team_members_with_cards(team.role)
        options = [discord.SelectOption(label="NPC (boş bırak)", value="__npc__", description="Bu mevkiye NPC oyuncu konur")]
        for member, card in members_cards[:24]:
            tier, _ = tier_info(card["value"])
            options.append(discord.SelectOption(
                label=f"{card['name']} ({card['value']}M, {tier})"[:100],
                description=f"Kayıtlı mevki: {card['position']} | {member.display_name}"[:100],
                value=str(member.id),
            ))
        select = discord.ui.Select(placeholder="Oyuncu seç...", options=options, min_values=1, max_values=1)
        select.callback = self.on_select
        self.add_item(select)

    async def on_select(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        if value == "__npc__":
            npc_val = random.randint(20, 90)
            card = {"name": "NPC Oyuncu", "value": npc_val, "country": "🏳️", "position": base_position(self.slot)}
            self.team.lineup[self.slot] = {"member": None, "card": card}
        else:
            member = interaction.guild.get_member(int(value))
            card = get_member_card(member) or {"name": member.display_name, "value": 0, "country": "🏳️", "position": base_position(self.slot)}
            self.team.lineup[self.slot] = {"member": member, "card": card}

        view = LineupPanelView(self.match, self.team)
        await interaction.response.edit_message(
            content=f"**{self.team.emoji} {self.team.name}** kadrosu:\n" + lineup_text(self.team),
            embed=None, view=view,
        )


def lineup_text(team: TeamSide) -> str:
    lines = []
    for slot, label in FORMATION_SLOTS:
        if slot in team.lineup:
            c = team.lineup[slot]["card"]
            mismatch = "⚠️ pozisyon dışı" if c["position"] != base_position(slot) else ""
            lines.append(f"`{slot:<4}` {label}: **{format_card(c)}** {mismatch}")
        else:
            lines.append(f"`{slot:<4}` {label}: *boş*")
    return "\n".join(lines)


async def advance_match_stage(interaction: discord.Interaction, match: Match):
    if match.stage == "kadro1":
        match.stage = "kadro2"
        view = LineupPanelView(match, match.team2)
        await interaction.followup.send(
            content=f"Sıra **{match.team2.emoji} {match.team2.name}** kadrosunda.\n" + lineup_text(match.team2),
            view=view,
        )
    elif match.stage == "kadro2":
        match.stage = "gorev1"
        view = DutyPickView(match, match.team1)
        await interaction.followup.send(
            content=f"**{match.team1.emoji} {match.team1.name}** için görevleri seçin (kaptan / korner / frikik / penaltı).",
            view=view,
        )
    elif match.stage == "gorev1":
        match.stage = "gorev2"
        view = DutyPickView(match, match.team2)
        await interaction.followup.send(
            content=f"**{match.team2.emoji} {match.team2.name}** için görevleri seçin (kaptan / korner / frikik / penaltı).",
            view=view,
        )
    elif match.stage == "gorev2":
        match.stage = "hazir"
        view = StartMatchView(match)
        await interaction.followup.send(
            content="Kadrolar ve görevler tamam! Maçı başlatmak için butona bas.",
            view=view,
        )


# ----------------------------------------------------------------------------
# UI: GÖREV (kaptan/korner/frikik/penaltı) SEÇİMİ
# ----------------------------------------------------------------------------

DUTY_LABELS = {"kaptan": "🎖️ Kaptan", "korner": "🚩 Korner Atan", "frikik": "🎯 Frikik Atan", "penaltı": "🥅 Penaltı Atan"}

class DutySelect(discord.ui.Select):
    def __init__(self, match: Match, team: TeamSide, duty_key: str):
        self.match = match
        self.team = team
        self.duty_key = duty_key
        options = []
        for slot, _ in FORMATION_SLOTS:
            info = team.lineup.get(slot)
            if info:
                options.append(discord.SelectOption(label=f"{info['card']['name']} ({slot})"[:100], value=slot))
        super().__init__(placeholder=f"{DUTY_LABELS[duty_key]} seç...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        self.team.duties[self.duty_key] = self.values[0]
        await interaction.response.send_message(
            f"{DUTY_LABELS[self.duty_key]}: **{self.team.lineup[self.values[0]]['card']['name']}** olarak ayarlandı.",
            ephemeral=True,
        )


class DutyPickView(discord.ui.View):
    def __init__(self, match: Match, team: TeamSide):
        super().__init__(timeout=300)
        self.match = match
        self.team = team
        for duty_key in DUTY_LABELS:
            self.add_item(DutySelect(match, team, duty_key))

    @discord.ui.button(label="Görevleri Onayla", style=discord.ButtonStyle.green, row=4)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        missing = [DUTY_LABELS[k] for k, v in self.team.duties.items() if v is None]
        if missing:
            # otomatik ata: kaptan yoksa ilk oyuncu, korner/frikik/penaltı yoksa rastgele
            slots = list(self.team.lineup.keys())
            for k in self.team.duties:
                if self.team.duties[k] is None:
                    self.team.duties[k] = random.choice(slots)
        summary = "\n".join(f"{DUTY_LABELS[k]}: **{self.team.lineup[v]['card']['name']}**" for k, v in self.team.duties.items())
        await interaction.response.edit_message(content=f"**{self.team.name}** görevleri:\n{summary}", view=None)
        await advance_match_stage(interaction, self.match)


class StartMatchView(discord.ui.View):
    def __init__(self, match: Match):
        super().__init__(timeout=600)
        self.match = match

    @discord.ui.button(label="⚽ Maçı Başlat", style=discord.ButtonStyle.blurple)
    async def start(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.match.starter_id:
            await interaction.response.send_message("Sadece maçı kuran kişi başlatabilir.", ephemeral=True)
            return
        await interaction.response.edit_message(content="Maç başlıyor! 🟢", view=None)
        self.match.stage = "oynaniyor"
        await run_match_simulation(interaction.channel, self.match)


# ----------------------------------------------------------------------------
# MAÇ SİMÜLASYON MOTORU
# ----------------------------------------------------------------------------

def pitch_bar(position_pct: float) -> str:
    """position_pct: 0 = takim1 kalesi, 100 = takim2 kalesi"""
    length = 20
    idx = max(0, min(length - 1, round(position_pct / 100 * (length - 1))))
    bar = ["▬"] * length
    bar[idx] = "⚽"
    return f"🥅|{''.join(bar)}|🥅"


def pick_weighted_player(team: TeamSide, exclude_gk=True):
    """Değere göre ağırlıklı, pozisyon uyumsuzluğu cezası uygulanmış rastgele oyuncu seç."""
    candidates = []
    weights = []
    for slot, info in team.lineup.items():
        if exclude_gk and slot == "KL":
            continue
        card = info["card"]
        tier, mult = tier_info(card["value"])
        if card["position"] != base_position(slot):
            mult *= 0.35
        candidates.append((slot, info))
        weights.append(max(0.05, mult))
    if not candidates:
        return None
    return random.choices(candidates, weights=weights, k=1)[0]


def get_keeper(team: TeamSide):
    info = team.lineup.get("KL")
    return ("KL", info) if info else None


def effective_rating(card: dict, slot: str) -> float:
    _, mult = tier_info(card["value"])
    if card["position"] != base_position(slot):
        mult *= 0.35
    return mult


async def run_match_simulation(channel: discord.TextChannel, match: Match):
    t1, t2 = match.team1, match.team2
    await channel.send(embed=discord.Embed(
        title=f"{t1.emoji} {t1.name}  0 - 0  {t2.name} {t2.emoji}",
        description="🎙️ Spiker: Maç başlıyor, taraftarlar tribünlerde yerini aldı!",
        color=discord.Color.green(),
    ))

    event_count = random.randint(22, 30)
    minutes = sorted(random.sample(range(1, 91), event_count))

    for minute in minutes:
        await asyncio.sleep(1.2)
        attacking, defending = (t1, t2) if random.random() < 0.5 else (t2, t1)
        attacker_slot_info = pick_weighted_player(attacking)
        if not attacker_slot_info:
            continue
        att_slot, att_info = attacker_slot_info
        att_card = att_info["card"]
        att_rating = effective_rating(att_card, att_slot)

        ball_pos = random.uniform(55, 95) if attacking is t1 else random.uniform(5, 45)
        bar = pitch_bar(ball_pos)

        event_roll = random.random()
        embed = discord.Embed(color=discord.Color.blurple())
        embed.set_footer(text=bar)

        # olay türü seçimi
        if event_roll < 0.12:
            # korner
            taker_slot = attacking.duties.get("korner") or att_slot
            taker = attacking.lineup.get(taker_slot, att_info)["card"]
            embed.description = f"**{minute}.dk** 🚩 Korner! {attacking.name} adına **{taker['name']}** korneri kullanıyor..."
            if random.random() < 0.22 * effective_rating(taker, taker_slot):
                scorer = att_card
                assist_member = att_info["member"]
                await handle_goal(channel, match, attacking, defending, minute, taker, scorer, from_set_piece="korner")
            else:
                embed.description += "\nTop kaleci tarafından uzaklaştırıldı."
                kp = get_keeper(defending)
                if kp:
                    add_stat_for(kp[1], "kurtarış")
                await channel.send(embed=embed)

        elif event_roll < 0.20:
            # frikik
            taker_slot = attacking.duties.get("frikik") or att_slot
            taker = attacking.lineup.get(taker_slot, att_info)["card"]
            embed.description = f"**{minute}.dk** 🎯 Frikik kazanıldı! **{taker['name']}** topun başında..."
            await channel.send(embed=embed)
            await asyncio.sleep(1.0)
            if random.random() < 0.18 * effective_rating(taker, taker_slot):
                await handle_goal(channel, match, attacking, defending, minute, taker, taker, from_set_piece="frikik")
            else:
                kp = get_keeper(defending)
                msg = discord.Embed(description=f"Frikik kaleciden döndü! 🧤 **{kp[1]['card']['name'] if kp else 'Kaleci'}** harika bir kurtarış yaptı.", color=discord.Color.orange())
                if kp:
                    add_stat_for(kp[1], "kurtarış")
                await channel.send(embed=msg)

        elif event_roll < 0.26:
            # penaltı (nadir)
            if random.random() < 0.35:
                taker_slot = attacking.duties.get("penaltı") or att_slot
                taker = attacking.lineup.get(taker_slot, att_info)["card"]
                embed.description = f"**{minute}.dk** 🥅 PENALTI! {attacking.name} için penaltı kazanıldı, **{taker['name']}** noktanın başında!"
                await channel.send(embed=embed)
                await asyncio.sleep(1.2)
                if random.random() < 0.75 * effective_rating(taker, taker_slot):
                    await handle_goal(channel, match, attacking, defending, minute, taker, taker, from_set_piece="penaltı")
                else:
                    kp = get_keeper(defending)
                    if kp:
                        add_stat_for(kp[1], "kurtarış")
                    await channel.send(embed=discord.Embed(description=f"Penaltı kaçtı! 🧤 Kaleci **{kp[1]['card']['name'] if kp else '?'}** yönünü bildi!", color=discord.Color.orange()))
            else:
                embed.description = f"**{minute}.dk** Ceza sahası karışıklığı ama hakem penaltı vermedi."
                await channel.send(embed=embed)

        elif event_roll < 0.45:
            # şut / gol denemesi
            defender_slot_info = pick_weighted_player(defending)
            embed.description = (
                f"**{minute}.dk** ⚽ {attacking.name} atakta! **{att_card['name']}** ({att_slot}) topu taşıyor, "
                f"paslarla ceza sahasına giriyor..."
            )
            await channel.send(embed=embed)
            await asyncio.sleep(1.0)

            if defender_slot_info and random.random() < 0.4 * effective_rating(defender_slot_info[1]["card"], defender_slot_info[0]):
                d_slot, d_info = defender_slot_info
                add_stat_for(d_info, "mudahale")
                await channel.send(embed=discord.Embed(
                    description=f"🛡️ Müthiş müdahale! **{d_info['card']['name']}** ({d_slot}) topu kesti.",
                    color=discord.Color.red(),
                ))
            elif random.random() < 0.5 * att_rating:
                # asist ihtimali
                assist_slot_info = pick_weighted_player(attacking)
                assister_card = assist_slot_info[1]["card"] if (assist_slot_info and assist_slot_info[0] != att_slot) else None
                await handle_goal(channel, match, attacking, defending, minute, assister_card, att_card)
            else:
                kp = get_keeper(defending)
                if kp and random.random() < 0.7:
                    add_stat_for(kp[1], "kurtarış")
                    await channel.send(embed=discord.Embed(
                        description=f"🧤 Kaleci **{kp[1]['card']['name']}** kurtarışı yapıyor! Gol yok.",
                        color=discord.Color.orange(),
                    ))
                else:
                    await channel.send(embed=discord.Embed(description="Şut auta gidiyor, gol yok.", color=discord.Color.greyple()))

        else:
            # normal pas / orta saha hareketi
            second_slot_info = pick_weighted_player(attacking)
            second_name = second_slot_info[1]["card"]["name"] if second_slot_info else "takım arkadaşı"
            embed.description = f"**{minute}.dk** 🔄 {attacking.name} topu kontrol ediyor: **{att_card['name']}** → **{second_name}** arasında paslaşma."
            await channel.send(embed=embed)

    # maç sonu
    await asyncio.sleep(1)
    result_embed = discord.Embed(
        title=f"🏁 MAÇ SONUCU: {t1.emoji} {t1.name}  {t1.score} - {t2.score}  {t2.name} {t2.emoji}",
        color=discord.Color.gold(),
    )
    result_embed.add_field(name=f"{t1.name} Kadro", value=lineup_text(t1), inline=False)
    result_embed.add_field(name=f"{t2.name} Kadro", value=lineup_text(t2), inline=False)
    await channel.send(embed=result_embed)

    match.stage = "bitti"
    active_matches.pop(match.channel_id, None)


def add_stat_for(info: dict, stat: str, amount: int = 1):
    member = info.get("member")
    if member is not None:
        add_stat(member.id, stat, amount)


async def handle_goal(channel, match: Match, attacking: TeamSide, defending: TeamSide, minute: int, assister_card, scorer_card, from_set_piece=None):
    attacking.score += 1
    desc = f"**{minute}.dk ⚽ GOOOL!** {attacking.name} için **{scorer_card['name']}** golü buluyor!"
    if from_set_piece:
        desc += f" ({from_set_piece} sonucu)"
    if assister_card and assister_card is not scorer_card:
        desc += f"\n🅰️ Asist: **{assister_card['name']}**"

    embed = discord.Embed(description=desc, color=discord.Color.green())
    embed.set_footer(text=f"Skor: {match.team1.name} {match.team1.score} - {match.team2.score} {match.team2.name}")
    await channel.send(embed=embed)

    # istatistik güncelle (üye ise)
    for team in (attacking,):
        for slot, info in team.lineup.items():
            if info["card"] is scorer_card:
                add_stat_for(info, "gol")
            if assister_card and info["card"] is assister_card:
                add_stat_for(info, "asist")


# ----------------------------------------------------------------------------
# KOMUTLAR: DEĞER YÖNETİMİ (ayrı kart veritabanı yok — doğrudan nickname okunur/yazılır)
# Format: İsim | DeğerM | Ülke | Mevki   (örn: Ronaldo | 100M | 🇵🇹 | SNT)
# Bir üyenin nicki zaten bu formattaysa bot otomatik tanır; .dver/.dsil ile
# değeri değiştirdiğinde bot nicki de buna göre günceller.
# ----------------------------------------------------------------------------

DEFAULT_CARD = lambda member: {"name": member.display_name, "value": 0, "country": "🏳️", "position": "OS"}

async def apply_card_to_nick(ctx, member: discord.Member, card: dict):
    new_nick = build_nick(card)
    try:
        await member.edit(nick=new_nick)
    except discord.Forbidden:
        await ctx.send(
            f"⚠️ {member.mention} kullanıcısının nickini değiştirecek yetkim yok "
            f"(rol sırası ya da izin sorunu). Hesaplanan değer: **{format_card(card)}**\n"
            f"Bunu manuel olarak nickine yazabilirsin."
        )
        return False
    await ctx.send(f"✅ {member.mention} güncellendi: **{new_nick}**")
    return True


@bot.command(name="dver")
@commands.has_permissions(manage_guild=True)
async def dver(ctx, member: discord.Member, miktar: int, *, yeni_isim: str = None):
    """Kullanıcının değerini artırır (milyon) ve istenirse ismini değiştirir. Nicki günceller."""
    card = get_member_card(member) or DEFAULT_CARD(member)
    card["value"] = max(0, card["value"] + miktar)
    if yeni_isim:
        card["name"] = yeni_isim
    await apply_card_to_nick(ctx, member, card)


@bot.command(name="dsil")
@commands.has_permissions(manage_guild=True)
async def dsil(ctx, member: discord.Member, miktar: int, *, yeni_isim: str = None):
    """Kullanıcının değerini azaltır (milyon) ve istenirse ismini değiştirir. Nicki günceller."""
    card = get_member_card(member) or DEFAULT_CARD(member)
    card["value"] = max(0, card["value"] - miktar)
    if yeni_isim:
        card["name"] = yeni_isim
    await apply_card_to_nick(ctx, member, card)


@bot.command(name="dpoz")
@commands.has_permissions(manage_guild=True)
async def dpoz(ctx, member: discord.Member, mevki: str):
    """Kullanıcının mevkisini ayarlar. .dpoz @kullanıcı SNT"""
    mevki_up = mevki.upper()
    if mevki_up not in ALL_POSITIONS:
        await ctx.send(f"Geçersiz mevki. Geçerli mevkiler: {', '.join(ALL_POSITIONS)}")
        return
    card = get_member_card(member) or DEFAULT_CARD(member)
    card["position"] = mevki_up
    await apply_card_to_nick(ctx, member, card)


@bot.command(name="dulke")
@commands.has_permissions(manage_guild=True)
async def dulke(ctx, member: discord.Member, ulke: str):
    """Kullanıcının ülke bayrağını ayarlar. .dulke @kullanıcı 🇵🇹"""
    card = get_member_card(member) or DEFAULT_CARD(member)
    card["country"] = ulke
    await apply_card_to_nick(ctx, member, card)


@bot.command(name="kart")
async def kart(ctx, member: discord.Member = None):
    """Bir kullanıcının mevcut nickinden okunan kartı gösterir."""
    member = member or ctx.author
    card = get_member_card(member)
    if not card:
        await ctx.send(f"{member.display_name} nicki `İsim | Değer | Ülke | Mevki` formatında değil, kart okunamadı.")
        return
    tier, _ = tier_info(card["value"])
    embed = discord.Embed(title=format_card(card), description=f"Seviye: **{tier}**", color=discord.Color.blue())
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


# ----------------------------------------------------------------------------
# KOMUT: MAÇ BAŞLAT
# ----------------------------------------------------------------------------

@bot.command(name="mac")
async def mac(ctx, takim1: discord.Role, takim2: discord.Role):
    if ctx.channel.id in active_matches:
        await ctx.send("Bu kanalda zaten devam eden bir maç var.")
        return
    if takim1.id not in TEAM_INFO or takim2.id not in TEAM_INFO:
        await ctx.send("Geçersiz takım rolü. Lütfen aktif takımlardan birini etiketleyin.")
        return
    if takim1.id == takim2.id:
        await ctx.send("İki farklı takım seçmelisin.")
        return

    t1 = TeamSide(takim1)
    t2 = TeamSide(takim2)
    match = Match(ctx.channel.id, t1, t2, ctx.author.id)
    active_matches[ctx.channel.id] = match

    intro = discord.Embed(
        title=f"{t1.emoji} {t1.name}  vs  {t2.name} {t2.emoji}",
        description="Kadro seçim paneli açılıyor...",
        color=discord.Color.dark_green(),
    )
    await ctx.send(embed=intro)

    view = LineupPanelView(match, t1)
    await ctx.send(content=f"**{t1.emoji} {t1.name}** kadrosunu seçin:\n" + lineup_text(t1), view=view)


# ----------------------------------------------------------------------------
# KOMUTLAR: İSTATİSTİK
# ----------------------------------------------------------------------------

@bot.command(name="s")
async def s(ctx, member: discord.Member = None):
    member = member or ctx.author
    st = get_stats(member.id)
    embed = discord.Embed(title=f"📊 {member.display_name} İstatistikleri", color=discord.Color.teal())
    for stat in STAT_TYPES:
        embed.add_field(name=STAT_LABELS[stat], value=str(st.get(stat, 0)), inline=True)
    embed.set_thumbnail(url=member.display_avatar.url)
    await ctx.send(embed=embed)


@bot.command(name="lb")
async def lb(ctx, tur: str):
    tur = tur.lower()
    alias = {"kurtaris": "kurtarış", "mudahale": "mudahale", "gol": "gol", "asist": "asist", "kurtarış": "kurtarış"}
    tur = alias.get(tur, tur)
    if tur not in STAT_TYPES:
        await ctx.send(f"Geçersiz tür. Seçenekler: {', '.join(STAT_TYPES)}")
        return

    rows = []
    for uid, st in DATA["stats"].items():
        val = st.get(tur, 0)
        if val > 0:
            rows.append((uid, val))
    rows.sort(key=lambda x: x[1], reverse=True)
    rows = rows[:10]

    if not rows:
        await ctx.send("Henüz veri yok.")
        return

    lines = []
    for i, (uid, val) in enumerate(rows, start=1):
        member = ctx.guild.get_member(int(uid))
        name = member.display_name if member else f"Kullanıcı {uid}"
        lines.append(f"**{i}.** {name} — {val}")

    embed = discord.Embed(title=f"🏆 {STAT_LABELS[tur]} Sıralaması", description="\n".join(lines), color=discord.Color.gold())
    await ctx.send(embed=embed)


@bot.command(name="statekle")
@commands.has_permissions(manage_guild=True)
async def statekle(ctx, member: discord.Member, tur: str, sayi: int):
    tur = tur.lower()
    if tur not in STAT_TYPES:
        await ctx.send(f"Geçersiz tür. Seçenekler: {', '.join(STAT_TYPES)}")
        return
    add_stat(member.id, tur, sayi)
    await ctx.send(f"✅ {member.mention} için {STAT_LABELS[tur]} +{sayi} eklendi. Yeni değer: {get_stats(member.id)[tur]}")


@bot.command(name="statsil")
@commands.has_permissions(manage_guild=True)
async def statsil(ctx, member: discord.Member, tur: str, sayi: int):
    tur = tur.lower()
    if tur not in STAT_TYPES:
        await ctx.send(f"Geçersiz tür. Seçenekler: {', '.join(STAT_TYPES)}")
        return
    add_stat(member.id, tur, -sayi)
    await ctx.send(f"✅ {member.mention} için {STAT_LABELS[tur]} -{sayi} silindi. Yeni değer: {get_stats(member.id)[tur]}")


# ----------------------------------------------------------------------------
# YARDIM
# ----------------------------------------------------------------------------

@bot.command(name="yardim")
async def yardim(ctx):
    embed = discord.Embed(title="📖 Komutlar", color=discord.Color.purple())
    embed.add_field(name="Değer Yönetimi (yetkili) — kart yok, doğrudan nickname kullanılır", value=(
        "Format: `İsim | DeğerM | Ülke | Mevki` (örn: Ronaldo | 100M | 🇵🇹 | SNT)\n"
        "Bir üyenin nicki zaten bu formattaysa panelde otomatik seçilebilir olur.\n"
        ".dver @kullanıcı <miktar> [yeni isim] — değer artırır, nicki günceller\n"
        ".dsil @kullanıcı <miktar> [yeni isim] — değer azaltır, nicki günceller\n"
        ".dpoz @kullanıcı <mevki> — mevki ayarlar\n"
        ".dulke @kullanıcı <bayrak> — ülke ayarlar\n"
        ".kart [@kullanıcı] — nickten okunan kartı gösterir"
    ), inline=False)
    embed.add_field(name="Maç", value="!mac @takim1 @takim2 — maç başlatır, kadro paneli açılır", inline=False)
    embed.add_field(name="İstatistik", value=(
        ".s [@kullanıcı] — istatistikleri gösterir\n"
        ".lb gol/asist/mudahale/kurtarış — sıralama\n"
        ".statekle @kullanıcı <tür> <sayı> — (yetkili) istatistik ekler\n"
        ".statsil @kullanıcı <tür> <sayı> — (yetkili) istatistik siler"
    ), inline=False)
    embed.add_field(name="Mevkiler", value=", ".join(ALL_POSITIONS), inline=False)
    embed.add_field(name="⚠️ Not", value=(
        "Nickname otomatik değişebilmesi için botun **\"Takma Adları Yönet\"** iznine sahip olması "
        "ve rolünün, nicki değişecek üyelerin rolünden **yukarıda** olması gerekir."
    ), inline=False)
    embed.set_footer(text="Komutlar hem . hem ! öneki ile çalışır (örn: .dver / !dver, !mac / .mac)")
    await ctx.send(embed=embed)


# ----------------------------------------------------------------------------
# HATA YÖNETİMİ
# ----------------------------------------------------------------------------

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Bu komutu kullanmak için yetkin yok.")
    elif isinstance(error, commands.MemberNotFound):
        await ctx.send("❌ Kullanıcı bulunamadı.")
    elif isinstance(error, commands.RoleNotFound):
        await ctx.send("❌ Rol bulunamadı.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Eksik parametre: `{error.param.name}`. `.yardim` yazarak komutları görebilirsin.")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Parametre hatalı. `.yardim` yazarak doğru kullanımı görebilirsin.")
    else:
        raise error


@bot.event
async def on_ready():
    print(f"Giriş yapıldı: {bot.user} ({bot.user.id})")


if __name__ == "__main__":
    if BOT_TOKEN == "BURAYA_BOT_TOKENINI_YAZ":
        print("UYARI: BOT_TOKEN ayarlanmadı. Dosyanın başındaki BOT_TOKEN değişkenine ya da "
              "DISCORD_BOT_TOKEN ortam değişkenine tokenini yaz.")
    bot.run(BOT_TOKEN)
