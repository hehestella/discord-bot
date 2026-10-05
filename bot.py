import json
import os
from threading import Thread
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask

# ==================== [웹 서버 설정 (24시간 유지용)] ====================
app = Flask("")


@app.route("/")
def home():
  return "Discord Bot is alive!"


def run_web():
  # Render 등에서 제공하는 포트(환경 변수 PORT)를 사용하거나 기본 8080 사용
  port = int(os.environ.get("PORT", 8080))
  app.run(host="0.0.0.0", port=port)


def keep_alive():
  t = Thread(target=run_web)
  t.start()


# ======================================================================

# 1. 봇 인텐트 설정
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# 데이터 파일 경로 설정
DATA_FILE = "bot_data.json"


# 데이터 로드 함수
def load_data():
  if os.path.exists(DATA_FILE):
    with open(DATA_FILE, "r", encoding="utf-8") as f:
      try:
        return json.load(f)
      except json.JSONDecodeError:
        return {"points": {}, "shop": {}, "quizzes": []}
  return {"points": {}, "shop": {}, "quizzes": []}


# 데이터 저장 함수
def save_data():
  data = {"points": user_points, "shop": shop_items, "quizzes": quiz_list}
  with open(DATA_FILE, "w", encoding="utf-8") as f:
    json.dump(data, f, ensure_ascii=False, indent=4)


# 데이터 불러오기 실행
db = load_data()
user_points = {int(k): v for k, v in db.get("points", {}).items()}
shop_items = db.get("shop", {})
quiz_list = db.get("quizzes", [])

current_quiz = None

# ==================== [채널 ID 설정 영역] ====================
LOG_CHANNEL_ID = 1556263403163615282  # 포인트 획득/사용 로그가 올라갈 채널 ID
ADMIN_LOG_CHANNEL_ID = 1556263403163615282  # 관리자의 포인트 지급/차감/제품등록 로그가 올라갈 채널 ID
# ============================================================

# 고정 흰색 컬러 (Hex: #FFFFFF)
WHITE_COLOR = discord.Color.from_rgb(255, 255, 255)


# 동적 상점 구매를 위한 버튼 뷰 (UI)
class ShopView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=180)

    for item_name, info in shop_items.items():
      price = info["price"]
      button = discord.ui.Button(
          label=f"{item_name} ({price} 포인트)",
          style=discord.ButtonStyle.green,
          custom_id=item_name,
      )
      button.callback = self.button_callback
      self.add_item(button)

  async def button_callback(self, interaction: discord.Interaction):
    item_name = interaction.data["custom_id"]
    if item_name not in shop_items:
      await interaction.response.send_message(
          "존재하지 않거나 삭제된 상품입니다.", ephemeral=True
      )
      return

    price = shop_items[item_name]["price"]
    role_name = shop_items[item_name]["role"]
    user_id = interaction.user.id

    current_pts = user_points.get(user_id, 0)

    if current_pts < price:
      await interaction.response.send_message(
          f"포인트가 부족합니다. 현재 보유 포인트: {current_pts} 포인트",
          ephemeral=True,
      )
      return

    role = discord.utils.get(interaction.guild.roles, name=role_name)
    if not role:
      await interaction.response.send_message(
          f"서버에 '{role_name}' 역할이 존재하지 않습니다. 관리자에게 문의하세요.",
          ephemeral=True,
      )
      return

    try:
      user_points[user_id] -= price
      save_data()

      await interaction.user.add_roles(role)
      await interaction.response.send_message(
          f"'{item_name}' 구매가 완료되었습니다! 남은 포인트: {user_points[user_id]}"
          " 포인트",
          ephemeral=True,
      )

      # 포인트 사용 로그 전송
      if LOG_CHANNEL_ID != 0:
        log_channel = interaction.guild.get_channel(LOG_CHANNEL_ID)
        if log_channel:
          embed = discord.Embed(
              title="포인트 사용 로그",
              description=(
                  f"**대상:** {interaction.user.mention} ({interaction.user.name})\n"
                  f"**내역:** '{item_name}' (역할: {role_name}) 구매\n"
                  f"**사용 포인트:** -{price} 포인트\n"
                  f"**잔여 포인트:** {user_points[user_id]} 포인트"
              ),
              color=WHITE_COLOR,
          )
          await log_channel.send(embed=embed)

    except Exception as e:
      await interaction.response.send_message(
          "역할을 지급하는 중 오류가 발생했습니다. 권한 설정을 확인해주세요.",
          ephemeral=True,
      )


@bot.event
async def on_ready():
  print(f"로그인 완료: {bot.user.name}")
  try:
    for guild in bot.guilds:
      synced = await bot.tree.sync(guild=guild)
      print(
          f"서버 '{guild.name}'에 총 {len(synced)}개의 명령어가 동기화되었습니다."
      )
  except Exception as e:
    print(e)


# /제품등록 명령어 (관리자 전용)
@bot.tree.command(
    name="제품등록", description="상점에 새로운 상품(역할)을 등록합니다. (관리자 전용)"
)
@app_commands.describe(
    제품명="상점에 표시될 이름", 가격="필요한 포인트", 역할="지급될 디스코드 역할 이름"
)
async def register_product(
    interaction: discord.Interaction, 제품명: str, 가격: int, 역할: str
):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if 가격 <= 0:
    await interaction.response.send_message(
        "가격은 0보다 커야 합니다.", ephemeral=True
    )
    return

  target_role = discord.utils.get(interaction.guild.roles, name=역할)
  if not target_role:
    await interaction.response.send_message(
        f"서버에 '{역할}' 이라는 이름의 역할이 존재하지 않습니다. 먼저 역할을"
        " 생성해주세요.",
        ephemeral=True,
    )
    return

  shop_items[제품명] = {"price": 가격, "role": 역할}
  save_data()

  await interaction.response.send_message(
      f"상점에 **{제품명}** 상품이 등록되었습니다! (가격: {가격}포인트, 지급 역할:"
      f" {역할})",
      ephemeral=True,
  )

  if ADMIN_LOG_CHANNEL_ID != 0:
    admin_log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if admin_log_channel:
      embed = discord.Embed(
          title="상점 제품 등록 로그",
          description=(
              f"**관리자:** {interaction.user.mention} ({interaction.user.name})\n"
              f"**등록 제품:** {제품명}\n"
              f"**가격:** {가격} 포인트\n"
              f"**연동 역할:** {역할}"
          ),
          color=WHITE_COLOR,
      )
      await admin_log_channel.send(embed=embed)


# /제품삭제 명령어 (관리자 전용)
@bot.tree.command(
    name="제품삭제", description="상점에서 등록된 제품을 삭제합니다. (관리자 전용)"
)
@app_commands.describe(제품명="삭제할 상점 제품 이름")
async def remove_product(interaction: discord.Interaction, 제품명: str):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if 제품명 not in shop_items:
    await interaction.response.send_message(
        f"상점에 '{제품명}' 이라는 제품이 존재하지 않습니다.", ephemeral=True
    )
    return

  del shop_items[제품명]
  save_data()

  await interaction.response.send_message(
      f"상점에서 **{제품명}** 제품이 삭제되었습니다.", ephemeral=True
  )

  if ADMIN_LOG_CHANNEL_ID != 0:
    admin_log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if admin_log_channel:
      embed = discord.Embed(
          title="상점 제품 삭제 로그",
          description=(
              f"**관리자:** {interaction.user.mention} ({interaction.user.name})\n"
              f"**삭제 제품:** {제품명}"
          ),
          color=WHITE_COLOR,
      )
      await admin_log_channel.send(embed=embed)


# /퀴즈등록 명령어 (관리자 전용)
@bot.tree.command(name="퀴즈등록", description="새로운 퀴즈를 등록합니다. (관리자 전용)")
@app_commands.describe(문제="출제할 문제 내용", 정답="퀴즈 정답", 힌트="멤버들에게 보여줄 힌트")
async def register_quiz(
    interaction: discord.Interaction, 문제: str, 정답: str, 힌트: str
):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  quiz_list.append({"question": 문제, "answer": 정답.strip(), "hint": 힌트})
  save_data()
  await interaction.response.send_message(
      f"퀴즈가 성공적으로 등록되었습니다. (총 등록된 퀴즈 수: {len(quiz_list)}개)",
      ephemeral=True,
  )


# /퀴즈목록 명령어 (관리자 전용)
@bot.tree.command(
    name="퀴즈목록",
    description=(
        "현재 등록된 퀴즈 리스트와 번호를 확인합니다. (관리자 전용)"
    ),
)
async def list_quizzes(interaction: discord.Interaction):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if not quiz_list:
    await interaction.response.send_message(
        "등록된 퀴즈가 없습니다.", ephemeral=True
    )
    return

  desc = ""
  for idx, q in enumerate(quiz_list):
    desc += f"**[{idx+1}]** 문제: {q['question']} / 정답: `{q['answer']}`\n"

  embed = discord.Embed(
      title="등록된 퀴즈 목록", description=desc, color=WHITE_COLOR
  )
  await interaction.response.send_message(embed=embed, ephemeral=True)


# /퀴즈삭제 명령어 (관리자 전용)
@bot.tree.command(
    name="퀴즈삭제",
    description="등록된 퀴즈 중 특정 번호의 퀴즈를 삭제합니다. (관리자 전용)",
)
@app_commands.describe(
    번호="/퀴즈목록 에서 확인한 삭제할 퀴즈 번호 (1부터 시작)"
)
async def remove_quiz(interaction: discord.Interaction, 번호: int):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if not quiz_list:
    await interaction.response.send_message(
        "삭제할 퀴즈가 없습니다.", ephemeral=True
    )
    return

  index = 번호 - 1
  if index < 0 or index >= len(quiz_list):
    await interaction.response.send_message(
        f"잘못된 번호입니다. 1부터 {len(quiz_list)} 사이의 번호를 입력해주세요.",
        ephemeral=True,
    )
    return

  removed = quiz_list.pop(index)
  save_data()

  await interaction.response.send_message(
      f"**[{번호}]** 퀴즈가 삭제되었습니다.\n(삭제된 문제: {removed['question']})",
      ephemeral=True,
  )


# /퀴즈 명령어 (누구나 사용 가능)
@bot.tree.command(
    name="퀴즈", description="등록된 퀴즈 중 하나를 출제합니다. (누구나 가능)"
)
async def start_quiz(interaction: discord.Interaction):
  if not quiz_list:
    await interaction.response.send_message(
        "등록된 퀴즈가 없습니다. 관리자에게 퀴즈 등록을 요청해주세요.",
        ephemeral=True,
    )
    return

  global current_quiz
  current_quiz = quiz_list[0]

  embed = discord.Embed(
      title="서버 퀴즈 타임",
      description=f"**문제:** {current_quiz['question']}\n\n정답을 채팅창에 입력해주세요!",
      color=WHITE_COLOR,
  )
  embed.add_field(name="힌트", value=current_quiz["hint"], inline=False)

  await interaction.response.send_message(embed=embed)


# 메시지 이벤트 감지 (정답 체크 및 포인트 적립 로그)
@bot.event
async def on_message(message):
  if message.author.bot:
    return

  global current_quiz
  if current_quiz and message.content.strip() == current_quiz["answer"]:
    user_id = message.author.id
    reward = 50

    user_points[user_id] = user_points.get(user_id, 0) + reward
    total_pts = user_points[user_id]
    save_data()

    await message.channel.send(
        f"정답입니다! {message.author.mention}님께서 정답을 맞혀 {reward} 포인트를"
        f" 획득하셨습니다!"
    )

    if LOG_CHANNEL_ID != 0:
      log_channel = message.guild.get_channel(LOG_CHANNEL_ID)
      if log_channel:
        embed = discord.Embed(
            title="포인트 획득 로그",
            description=(
                f"**대상:** {message.author.mention} ({message.author.name})\n"
                f"**사유:** 퀴즈 정답 맞힘\n"
                f"**획득 포인트:** +{reward} 포인트\n"
                f"**총 보유 포인트:** {total_pts} 포인트"
            ),
            color=WHITE_COLOR,
        )
        await log_channel.send(embed=embed)

    current_quiz = None
    if quiz_list:
      quiz_list.pop(0)
      save_data()

  await bot.process_commands(message)


# /포인트 명령어
@bot.tree.command(name="포인트", description="현재 나의 보유 포인트를 확인합니다.")
async def check_points(interaction: discord.Interaction):
  user_id = interaction.user.id
  pts = user_points.get(user_id, 0)
  await interaction.response.send_message(
      f"현재 보유하신 포인트는 {pts} 포인트입니다.", ephemeral=True
  )


# /포인트지급 명령어 (관리자 전용)
@bot.tree.command(
    name="포인트지급", description="특정 유저에게 포인트를 지급합니다. (관리자 전용)"
)
@app_commands.describe(대상="포인트를 받을 유저", 얼마나="지급할 포인트 양")
async def give_points(
    interaction: discord.Interaction, 대상: discord.Member, 얼마나: int
):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if 얼마나 <= 0:
    await interaction.response.send_message(
        "0보다 큰 포인트를 입력해주세요.", ephemeral=True
    )
    return

  user_points[대상.id] = user_points.get(대상.id, 0) + 얼마나
  total_pts = user_points[대상.id]
  save_data()

  await interaction.response.send_message(
      f"{대상.mention}님께 {얼마나} 포인트를 지급했습니다. (총 보유: {total_pts} 포인트)",
      ephemeral=True,
  )

  if ADMIN_LOG_CHANNEL_ID != 0:
    admin_log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if admin_log_channel:
      embed = discord.Embed(
          title="관리자 포인트 지급 로그",
          description=(
              f"**관리자:** {interaction.user.mention} ({interaction.user.name})\n"
              f"**지급 대상:** {대상.mention} ({대상.name})\n"
              f"**지급 포인트:** +{얼마나} 포인트\n"
              f"**대상의 총 보유 포인트:** {total_pts} 포인트"
          ),
          color=WHITE_COLOR,
      )
      await admin_log_channel.send(embed=embed)


# /포인트차감 명령어 (관리자 전용)
@bot.tree.command(
    name="포인트차감", description="특정 유저의 포인트를 차감합니다. (관리자 전용)"
)
@app_commands.describe(대상="포인트를 깎을 유저", 얼마나="차감할 포인트 양")
async def remove_points(
    interaction: discord.Interaction, 대상: discord.Member, 얼마나: int
):
  admin_role = discord.utils.get(interaction.user.roles, name="관리자")
  if not admin_role and not interaction.user.guild_permissions.administrator:
    await interaction.response.send_message(
        "이 명령어를 실행할 권한이 없습니다.", ephemeral=True
    )
    return

  if 얼마나 <= 0:
    await interaction.response.send_message(
        "0보다 큰 포인트를 입력해주세요.", ephemeral=True
    )
    return

  current_pts = user_points.get(대상.id, 0)
  new_pts = max(0, current_pts - 얼마나)
  user_points[대상.id] = new_pts
  save_data()

  await interaction.response.send_message(
      f"{대상.mention}님의 포인트를 {얼마나} 차감했습니다. (총 보유: {new_pts}"
      " 포인트)",
      ephemeral=True,
  )

  if ADMIN_LOG_CHANNEL_ID != 0:
    admin_log_channel = interaction.guild.get_channel(ADMIN_LOG_CHANNEL_ID)
    if admin_log_channel:
      embed = discord.Embed(
          title="관리자 포인트 차감 로그",
          description=(
              f"**관리자:** {interaction.user.mention} ({interaction.user.name})\n"
              f"**차감 대상:** {대상.mention} ({대상.name})\n"
              f"**차감 포인트:** -{얼마나} 포인트\n"
              f"**대상의 총 보유 포인트:** {new_pts} 포인트"
          ),
          color=WHITE_COLOR,
      )
      await admin_log_channel.send(embed=embed)


# /상점 명령어
@bot.tree.command(name="상점", description="포인트로 역할을 구매할 수 있는 상점을 엽니다.")
async def open_shop(interaction: discord.Interaction):
  if not shop_items:
    await interaction.response.send_message(
        "현재 등록된 상점 상품이 없습니다. 관리자에게 문의해주세요.",
        ephemeral=True,
    )
    return

  embed = discord.Embed(
      title="서버 포인트 상점",
      description="아래 버튼을 눌러 원하는 역할을 바로 구매할 수 있습니다.",
      color=WHITE_COLOR,
  )

  for item_name, info in shop_items.items():
    embed.add_field(
        name=item_name,
        value=f"가격: {info['price']} 포인트 / 지급 역할: {info['role']}",
        inline=False,
    )

  view = ShopView()
  await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# 봇 실행 전 웹 서버 켜기 (24시간 유지용)
keep_alive()

# 봇 실행 토큰 입력
bot.run("YOUR_BOT_TOKEN")