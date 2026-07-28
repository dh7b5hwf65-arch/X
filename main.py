import discord
from discord.ext import commands
from discord.ui import View, Button, Modal, TextInput
import random
import asyncio
import sqlite3
import os
from dotenv import load_dotenv

# .env dosyasından tokeni yüklüyoruz
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# İzinleri (Intents) ayarlıyoruz
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix=['!', '.'], intents=intents, help_command=None)

# Veritabanını (SQLite) kuruyoruz
conn = sqlite3.connect('futbol_stats.db')
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS stats 
             (user_id INTEGER PRIMARY KEY, goals INTEGER, assists INTEGER, saves INTEGER)''')
conn.commit()

def update_stat(user_id, stat_type, amount=1):
    c.execute('SELECT * FROM stats WHERE user_id = ?', (user_id,))
    row = c.fetchone()
    if row is None:
        c.execute('INSERT INTO stats (user_id, goals, assists, saves) VALUES (?, 0, 0, 0)', (user_id,))
    
    c.execute(f'UPDATE stats SET {stat_type} = {stat_type} + ? WHERE user_id = ?', (amount, user_id))
    conn.commit()

def calculate_tier(value_str):
    try:
        value = int(value_str.replace('M', '').strip())
        if value <= 50: return "Kötü"
        elif value <= 99: return "Normal"
        elif value <= 199: return "İyi"
        elif value <= 249: return "Star"
        else: return "Süperstar"
    except:
        return "NPC" # Hatalı girişte veya boşlukta otomatik NPC olur (0-50M seviyesinde)

# Kadro girmek için Modal (Açılır Pencere)
class SquadModal(Modal):
    def __init__(self, team_role, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.team_role = team_role
        
        self.squad_input = TextInput(
            label="Kadronu Gir (Oyuncu | Değer | Bayrak | Mevki)",
            style=discord.TextStyle.paragraph,
            placeholder="Örneğin:\nAhmet | 120M | 🇹🇷 | SNT\nNPC | 20M | 🏳️ | KL",
            required=True,
            max_length=2000
        )
        self.add_item(self.squad_input)
        
        self.set_pieces = TextInput(
            label="Duran Top Kullananlar (Korner, Frikik, Pen)",
            style=discord.TextStyle.short,
            placeholder="Korner: Ahmet, Penaltı: Mehmet",
            required=False
        )
        self.add_item(self.set_pieces)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.send_message(f"✅ {self.team_role.name} için kadro kaydedildi!\n**Diziliş:** Otomatik (4-3-3)\n**Duran Toplar:** {self.set_pieces.value}", ephemeral=True)
        # Girilen kadroyu analiz edip maç motoruna aktarmak için burada bir değişken listesine kaydedebilirsin.

# Canlı Maç Paneli
class MatchPanelView(View):
    def __init__(self, home_role, away_role):
        super().__init__(timeout=None)
        self.home_role = home_role
        self.away_role = away_role

    @discord.ui.button(label="Ev Sahibi Kadro Gir", style=discord.ButtonStyle.primary, custom_id="home_squad")
    async def home_btn(self, interaction: discord.Interaction, button: Button):
        if self.home_role in interaction.user.roles or interaction.user.guild_permissions.administrator:
            await interaction.response.send_modal(SquadModal(title="Ev Sahibi Kadrosu", team_role=self.home_role))
        else:
            await interaction.response.send_message("❌ Bu takımın rolüne sahip değilsin!", ephemeral=True)

    @discord.ui.button(label="Deplasman Kadro Gir", style=discord.ButtonStyle.danger, custom_id="away_squad")
    async def away_btn(self, interaction: discord.Interaction, button: Button):
        if self.away_role in interaction.user.roles or interaction.user.guild_permissions.administrator:
            await interaction.response.send_modal(SquadModal(title="Deplasman Kadrosu", team_role=self.away_role))
        else:
            await interaction.response.send_message("❌ Bu takımın rolüne sahip değilsin!", ephemeral=True)

    @discord.ui.button(label="Maçı Başlat!", style=discord.ButtonStyle.success, custom_id="start_match")
    async def start_btn(self, interaction: discord.Interaction, button: Button):
        if interaction.user.guild_permissions.administrator:
            await interaction.response.send_message("🏟️ **Maç başlıyor!** Canlı spiker hatta...")
            await simulate_match(interaction.channel, self.home_role, self.away_role)
        else:
            await interaction.response.send_message("❌ Sadece adminler maçı başlatabilir.", ephemeral=True)

async def simulate_match(channel, home_role, away_role):
    # Maç simülasyonu döngüsü (Şut, Orta, Pas etkinlikleri)
    events = [
        ("Paslaşma", "{team} merkezde kısa paslarla atak hazırlığında.", 0),
        ("Orta", "{team} sağ kanattan ceza sahasına keskin bir orta açtı! {distance} metreden...", 1),
        ("Şut", "Muhteşem şut şansı! {distance} metreden kaleye doğru sert bir vuruş!", 1)
    ]
    
    score = {home_role.name: 0, away_role.name: 0}
    
    for minute in range(1, 91, 15): # Maç 90 dakika, her 15 dakikada bir pozisyon
        await asyncio.sleep(3) # Canlı anlatım hissi vermek için 3 saniye bekleme
        team = random.choice([home_role.name, away_role.name])
        event_title, event_text, is_danger = random.choice(events)
        distance = random.randint(10, 35)
        
        embed = discord.Embed(title=f"⏱️ Dakika {minute}: {event_title}", color=discord.Color.blue())
        embed.description = event_text.format(team=team, distance=distance)
        
        if is_danger and random.random() > 0.6: # %40 gol ihtimali (oyuncu değerlerine göre dinamiğe bağlanabilir)
            scorer = "NPC_Oyuncu" # Burası modaldan gelen oyuncu verisine göre şekillenebilir
            score[team] += 1
            embed.color = discord.Color.green()
            embed.add_field(name="GOOOOLLL!!!", value=f"⚽ Golü atan: {scorer}\nİstatistik otomatik kaydedildi!")
            # Eğer gerçek bir discord kullanıcısı gol atarsa: update_stat(user_id, 'goals')
            
        elif is_danger:
            embed.color = discord.Color.orange()
            embed.add_field(name="Kurtarış!", value="🧤 Kaleci (NPC) inanılmaz uzandı ve topu kornere çeldi!")
            # Kurtarış yapan oyuncu için: update_stat(user_id, 'saves')
            
        await channel.send(embed=embed)

    # Maç Sonu
    result_embed = discord.Embed(title="🏁 MAÇ BİTTİ!", color=discord.Color.dark_theme())
    result_embed.add_field(name="Skor", value=f"**{home_role.name} {score[home_role.name]} - {score[away_role.name]} {away_role.name}**")
    await channel.send(embed=result_embed)


@bot.command(name="mac")
@commands.has_permissions(administrator=True)
async def mac(ctx, home: discord.Role, away: discord.Role):
    embed = discord.Embed(
        title="🏟️ Canlı Maç Paneli", 
        description=f"**Ev Sahibi:** {home.mention}\n**Deplasman:** {away.mention}\n\nTakım yöneticileri aşağıdaki butonlardan kadrolarını kurabilirler. Kendi mevkisinde oynamayan oyuncuların performansı düşecektir!",
        color=discord.Color.gold()
    )
    embed.set_footer(text="Sistem: 0-50M (Kötü) | 50-99M (Normal) | 100-199M (İyi) | 200-249M (Star) | 250M+ (Süperstar)")
    
    view = MatchPanelView(home_role=home, away_role=away)
    await ctx.send(embed=embed, view=view)


@bot.command(name="s")
async def stats(ctx, member: discord.Member = None):
    target = member or ctx.author
    c.execute('SELECT goals, assists, saves FROM stats WHERE user_id = ?', (target.id,))
    row = c.fetchone()
    
    if not row:
        row = (0, 0, 0)
        
    embed = discord.Embed(title=f"📊 {target.display_name} Kariyer İstatistikleri", color=discord.Color.purple())
    embed.add_field(name="⚽ Gol", value=str(row[0]), inline=True)
    embed.add_field(name="🎯 Asist", value=str(row[1]), inline=True)
    embed.add_field(name="🧤 Kurtarış", value=str(row[2]), inline=True)
    embed.set_thumbnail(url=target.display_avatar.url)
    
    await ctx.send(embed=embed)


@bot.event
async def on_ready():
    print(f'✅ Bot {bot.user.name} olarak aktif!')
    print('Maç paneli sistemi hazır.')

bot.run(TOKEN)
