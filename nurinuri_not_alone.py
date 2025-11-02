import streamlit as st
import pandas as pd
import random
import datetime
from gtts import gTTS
import base64
import io
import requests
from geopy.distance import geodesic

# ===================== #
# 기본 설정
# ===================== #
st.set_page_config(page_title="누리누리 - not alone!", layout="wide")

# 글자 크기 옵션
font_size = st.session_state.get("font_size", "일반")
size_map = {"소": "14px", "일반": "16px", "대형": "20px", "초대형": "26px"}

# 스타일 적용
st.markdown(f"""
    <style>
    body, input, textarea, button {{
        font-size: {size_map[font_size]} !important;
    }}
    </style>
""", unsafe_allow_html=True)

# 강아지 이미지
DOG_URL = "https://i.ibb.co/qjnB6Zq/cute-dog.png"  # 너가 준 URL로 바꿔도 됨

# ===================== #
# 유틸 함수들
# ===================== #

def tts_audio(text):
    """텍스트를 음성으로 변환해 Streamlit에서 재생"""
    tts = gTTS(text=text, lang="ko")
    fp = io.BytesIO()
    tts.write_to_fp(fp)
    fp.seek(0)
    st.audio(fp.read(), format="audio/mp3")

def get_weather_info():
    """위치 기반 날씨 정보 (Open-Meteo, API key 불필요)"""
    try:
        ipinfo = requests.get("https://ipinfo.io/json").json()
        lat, lon = map(float, ipinfo["loc"].split(","))
        weather = requests.get(
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true"
        ).json()
        temp = weather["current_weather"]["temperature"]
        code = weather["current_weather"]["weathercode"]
        desc = {
            0: "맑음 ☀️", 1: "대체로 맑음 🌤", 2: "구름 많음 ⛅", 3: "흐림 ☁️",
            45: "안개 🌫", 48: "안개 🌫", 51: "이슬비 🌦", 61: "비 🌧", 71: "눈 ❄️"
        }.get(code, "날씨 정보 없음")
        return temp, desc
    except:
        return None, "날씨 정보를 불러오지 못했습니다."

# ===================== #
# 탭 구성
# ===================== #
tabs = st.tabs([
    "🐶 매일 체크인", "💊 복약 리마인더", "🏥 병원 추천",
    "🧠 치매 예방 프로그램", "🚨 위험도 시나리오", "💬 똥강아지 대화"
])

checkins = st.session_state.get("checkins", [])
med_log = st.session_state.get("med_log", [])


# ---------------------------- 🐶 Daily Check-in (강아지 사진 클릭 기능) ----------------------------

st.subheader("🐾 오늘도 안녕, 똥강아지!")

# 강아지 이미지로 체크인 버튼 대체
dog_image_url = "https://i.imgur.com/YOUR_DOG_IMAGE.jpg"  # 사용자가 줄 URL
clicked = st.button("🐶 오늘 하루 인사하기")

if clicked:
    new_checkin = pd.DataFrame({
        "timestamp": [datetime.now()],
        "message": ["오늘도 잘 지냈어요!"]
    })
    checkins = pd.concat([checkins, new_checkin], ignore_index=True)
    checkins.to_csv(CHECKIN_FILE, index=False)
    st.success("오늘도 잘 지냈다고 기록했어요 💕")

st.image(dog_image_url, use_container_width=True)
st.caption("🐕 강아지를 눌러서 매일 안부를 남겨요!")

# 최근 기록 보여주기
if not checkins.empty:
    last = checkins.tail(3)
    st.write("📅 최근 기록")
    st.dataframe(last)

# ---------------------------- 🌤️ 날씨 정보 ----------------------------
st.subheader("🌤️ 오늘의 날씨")

# API 키 없이 무료 공개 API 사용
def get_weather():
    try:
        loc = geocoder.ip('me')
        lat, lon = loc.latlng
        url = f"https://wttr.in/{lat},{lon}?format=%C+%t"
        response = requests.get(url)
        if response.status_code == 200:
            return response.text
        return "날씨 정보를 불러오지 못했어요."
    except:
        return "위치를 확인할 수 없어요."

weather = get_weather()
st.info(f"현재 위치의 날씨: {weather}")

# ---------------------------- 🏥 근처 병원 추천 ----------------------------
st.subheader("🏥 근처 병원 추천")

def get_nearby_hospitals():
    try:
        loc = geocoder.ip('me')
        lat, lon = loc.latlng
        query = f"hospital near {lat},{lon}"
        url = f"https://nominatim.openstreetmap.org/search?q={query}&format=json&limit=5"
        res = requests.get(url)
        data = res.json()
        hospitals = [
            {"이름": h.get("display_name", "이름 없음"), "위도": h["lat"], "경도": h["lon"]}
            for h in data
        ]
        return pd.DataFrame(hospitals)
    except:
        return pd.DataFrame(columns=["이름", "위도", "경도"])

hospitals = get_nearby_hospitals()
if not hospitals.empty:
    st.map(hospitals.rename(columns={"위도": "lat", "경도": "lon"}))
    st.dataframe(hospitals)
else:
    st.warning("근처 병원을 찾을 수 없어요 😢")

# ---------------------------- 💊 복약 리마인더 및 상호작용 ----------------------------
st.subheader("💊 복약 리마인더")

# 복약 정보 입력
with st.form("med_form"):
    med_name = st.text_input("복용 중인 약 이름")
    med_time = st.time_input("복용 시간")
    submitted = st.form_submit_button("등록하기")

if submitted and med_name:
    new_med = pd.DataFrame({
        "약이름": [med_name],
        "시간": [med_time.strftime("%H:%M")]
    })
    meds = pd.concat([meds, new_med], ignore_index=True)
    meds.to_csv(MEDS_FILE, index=False)
    st.success(f"{med_name} 등록 완료!")

# 복약 정보 표시
if not meds.empty:
    st.dataframe(meds)

# 상호작용 예시 (단순 데이터)
interaction_data = {
    "타이레놀": ["술", "이부프로펜"],
    "이부프로펜": ["위장약", "타이레놀"],
    "항생제": ["유제품", "철분제"]
}

st.write("⚠️ 함께 먹으면 안 되는 음식/약물")

if not meds.empty:
    for _, row in meds.iterrows():
        name = row["약이름"]
        if name in interaction_data:
            bad_list = ", ".join(interaction_data[name])
            st.warning(f"❗ {name}과(와) 함께 섭취하면 안 되는 음식·약물: {bad_list}")
        else:
            st.info(f"{name}은(는) 현재 등록된 주의사항이 없어요.")

# 복약 알림 (시간 확인)
now = datetime.now().strftime("%H:%M")
due_meds = meds[meds["시간"] == now] if not meds.empty else pd.DataFrame()

if not due_meds.empty:
    st.error("💊 복용할 시간이에요!")
    for _, row in due_meds.iterrows():
        st.write(f"👉 {row['약이름']} 복용하세요!")


# ---------------------------- 🧩 치매 예방 프로그램 ----------------------------
st.header("🧩 치매 예방 프로그램")

mode = st.radio("훈련 모드 선택", ["기억력 퍼즐", "단어 퀴즈"])

if mode == "기억력 퍼즐":
    st.write("🧠 순서대로 숫자를 기억하세요!")
    if "puzzle_nums" not in st.session_state:
        st.session_state.puzzle_nums = random.sample(range(1, 10), 9)

    cols = st.columns(3)
    for i, col in enumerate(cols):
        col.button(str(st.session_state.puzzle_nums[i]), key=f"p{i}")

    if st.button("다시 섞기"):
        st.session_state.puzzle_nums = random.sample(range(1, 10), 9)
        st.experimental_rerun()

elif mode == "단어 퀴즈":
    words = ["사과", "바나나", "강아지", "학교", "커피"]
    answer = random.choice(words)
    st.write("💬 기억할 단어:", answer)
    time.sleep(2)
    st.write("이제 단어를 기억해보세요!")
    user_ans = st.text_input("기억한 단어를 입력하세요")
    if user_ans:
        if user_ans == answer:
            st.success("정답이에요! 기억력이 좋아요 😊")
        else:
            st.error(f"틀렸어요 😅 정답은 '{answer}' 였어요.")

# ---------------------------- 🚨 위험도 예측 시뮬레이션 ----------------------------
st.header("🚨 위험도 시뮬레이션")

def estimate_adherence(meds_df, med_log_df, days=7, window_minutes=60):
    now = datetime.now()
    from_dt = now - timedelta(days=days)
    due_total = 0
    taken_on_time = 0

    for _, med in meds_df.iterrows():
        due_time = datetime.combine(datetime.now().date(), datetime.strptime(med["시간"], "%H:%M").time())
        if from_dt <= due_time <= now:
            due_total += 1
            if not med_log_df.empty:
                med_log_df["taken_at"] = pd.to_datetime(med_log_df["taken_at"], errors="coerce")
                taken_list = med_log_df[
                    (med_log_df["약이름"] == med["약이름"]) &
                    (med_log_df["taken_at"] >= due_time - timedelta(minutes=window_minutes)) &
                    (med_log_df["taken_at"] <= due_time + timedelta(minutes=window_minutes))
                ]
                if not taken_list.empty:
                    taken_on_time += 1

    return due_total, taken_on_time

def risk_score(checkins, med_log, meds):
    score = 100
    if len(checkins) < 3:
        score -= 15
    if not meds.empty:
        due, taken = estimate_adherence(meds, med_log)
        if due > 0:
            adherence_rate = (taken / due) * 100
            score -= (100 - adherence_rate) * 0.3
    detail = f"현재 위험도 점수는 {int(score)}점이에요."
    return max(0, min(100, int(score))), detail

if st.button("📊 위험도 계산하기"):
    med_log_df = pd.DataFrame(columns=["약이름", "taken_at"])  # 더미 데이터
    score, detail = risk_score(checkins, med_log_df, meds)
    if score >= 80:
        st.success(f"🟢 안정 상태 ({score}점) - {detail}")
    elif score >= 50:
        st.warning(f"🟡 주의 필요 ({score}점) - {detail}")
    else:
        st.error(f"🔴 위험! ({score}점) - {detail}")

# ---------------------------- 🐾 음성 대화 ----------------------------
st.header("🐾 똥강아지와 대화하기")

def speak(text):
    tts = gTTS(text=text, lang='ko')
    tts.save("voice.mp3")
    st.audio("voice.mp3", autoplay=True)

user_input = st.text_input("똥강아지에게 말을 걸어보세요 🐶")
if user_input:
    if "기분" in user_input:
        reply = "저는 항상 행복해요! 주인님 덕분이에요 💕"
    elif "날씨" in user_input:
        reply = f"오늘은 {weather} 날씨예요. 산책 가고 싶어요!"
    elif "약" in user_input:
        reply = "약 챙겨 드셨나요? 까먹지 마세요 💊"
    else:
        reply = "멍멍! 잘 모르겠지만, 사랑해요 💖"
    st.write(f"🐶: {reply}")
    speak(reply)

# ---------------------------- 🔠 글자 크기 조절 ----------------------------
st.sidebar.header("🧩 설정")
font_size = st.sidebar.slider("글자 크기 조절", 12, 30, 18)
st.markdown(
    f"""
    <style>
    html, body, [class*="css"]  {{
        font-size: {font_size}px !important;
    }}
    </style>
    """,
    unsafe_allow_html=True
)
