# nurinuri_not_alone.py
# 실행: streamlit run nurinuri_not_alone.py
# requirements.txt 참고

import streamlit as st
import pandas as pd
import numpy as np
import pydeck as pdk
import requests
from datetime import datetime, timedelta, time as dtime
from io import BytesIO
from zoneinfo import ZoneInfo
import os, json, re, base64, math

KST = ZoneInfo("Asia/Seoul")

# ------------------------
# 파일 / 상수
# ------------------------
CHECKIN_CSV = "checkins.csv"
MEDS_CSV = "meds.csv"
MEDLOG_CSV = "med_log.csv"
INSTITUTIONS_CSV = "institutions.csv"
REGIONAL_CSV = "regional_factors.csv"
HOME_JSON = "home_location.json"
CONTACTS_JSON = "contacts.json"

# 강아지 이미지 (사용자가 준 URL 사용)
DOG_URL_IDLE = "https://marketplace.canva.com/yKgYw/MAGz2eyKgYw/1/tl/canva-cartoon-illustration-of-a-happy-brown-poodle-MAGz2eyKgYw.png"
DOG_URL_SMILE = "https://image.utoimage.com/preview/cp861283/2024/09/202409012057_500.jpg"

# ------------------------
# 간단 약물 상호작용 DB (예시, 필요한 만큼 확장 가능)
# ------------------------
DRUG_INTERACTIONS = {
    "warfarin": ["비타민K가 풍부한 음식(시금치 등)과 상호작용 가능 — 복용 규칙 준수 필요",
                 "NSAIDs(예: 이부프로펜)과 함께 쓰면 출혈 위험 증가"],
    "atorvastatin": ["그레이프프루트 주스는 혈중 농도 상승 가능 — 피하세요",
                     "일부 항생제(macrolide)와 병용 시 부작용 증가 가능"],
    "simvastatin": ["그레이프프루트 주스 금기", "강력한 CYP3A4 억제제와 병용 주의"],
    "metformin": ["과도한 음주 시 젖산산증 위험 증가 — 음주 주의"],
    "aspirin": ["다른 NSAIDs와 병용 시 출혈 위험 증가", "항응고제(와파린 등)와 병용 주의"],
    "amlodipine": ["자몽과 상호작용 보고 있음 — 주의"],
}

def lookup_interactions(drug_name: str):
    if not drug_name: return []
    name = str(drug_name).lower()
    warnings = []
    for k,v in DRUG_INTERACTIONS.items():
        if k in name or name in k:
            warnings += v
    tokens = re.split(r"[\s,/]+", name)
    for t in tokens:
        if t in DRUG_INTERACTIONS:
            warnings += DRUG_INTERACTIONS[t]
    # unique preserve order
    return list(dict.fromkeys(warnings))

# ------------------------
# 오디오(내장 톤) - 경보용
# ------------------------
def make_alarm_wav(seconds=1.2, freq=880, sr=16000):
    import wave, struct
    t = np.linspace(0, seconds, int(sr*seconds), False)
    tone = (0.5*np.sin(2*np.pi*freq*t)).astype(np.float32)
    buf = BytesIO()
    with wave.open(buf, 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        for s in tone:
            w.writeframes(struct.pack('<h', int(s*32767)))
    buf.seek(0)
    return buf.getvalue()

ALARM_WAV = make_alarm_wav()
ALARM_B64 = base64.b64encode(ALARM_WAV).decode()

# ------------------------
# 유틸 함수
# ------------------------
def now_kst():
    return datetime.now(KST)

def ensure_csv(path, cols):
    if not os.path.exists(path):
        pd.DataFrame(columns=cols).to_csv(path, index=False)

def save_csv(df, path):
    try:
        df.to_csv(path, index=False)
    except Exception:
        pass

def read_csv_flexible(path_or_buf):
    """한글 CSV 인코딩(utf-8-sig/CP949/EUC-KR/utf-8) 자동 시도"""
    encs = ["utf-8-sig", "cp949", "euc-kr", "utf-8", "latin1"]
    last_err = None
    # path_or_buf may be path string or an uploaded buffer
    if isinstance(path_or_buf, str):
        for e in encs:
            try:
                return pd.read_csv(path_or_buf, encoding=e)
            except Exception as err:
                last_err = err
                continue
        raise last_err
    else:
        raw = path_or_buf.read()
        for e in encs:
            try:
                return pd.read_csv(BytesIO(raw), encoding=e)
            except Exception:
                continue
        return pd.read_csv(BytesIO(raw))

def safe_read_csv(uploaded_or_path):
    return read_csv_flexible(uploaded_or_path)

def parse_time_str(tstr):
    try:
        h,m = map(int, str(tstr).split(":"))
        return dtime(hour=h, minute=m)
    except Exception:
        return None

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi = np.radians(lat2-lat1); dlambda = np.radians(lon2-lon1)
    a = np.sin(dphi/2.0)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlambda/2.0)**2
    return 2*R*np.arcsin(np.sqrt(a))

def load_home():
    if os.path.exists(HOME_JSON):
        try:
            with open(HOME_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None
    return None

def save_home(lat, lon, label="우리 집"):
    try:
        with open(HOME_JSON, "w", encoding="utf-8") as f:
            json.dump({"label": label, "lat": float(lat), "lon": float(lon)}, f, ensure_ascii=False)
        return True
    except Exception:
        return False

def load_contacts():
    if os.path.exists(CONTACTS_JSON):
        try:
            with open(CONTACTS_JSON, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_contacts(lst):
    try:
        with open(CONTACTS_JSON, "w", encoding="utf-8") as f:
            json.dump(lst, f, ensure_ascii=False)
    except Exception:
        pass

# ------------------------
# 체크인/시간 처리/위험도 로직 (친구 코드 기반 보존 및 개선)
# ------------------------
def ensure_timestamp(df: pd.DataFrame) -> pd.DataFrame:
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        # localize naive datetimes to KST if tz-naive
        try:
            naive = df["timestamp"].dt.tz is None
        except Exception:
            naive = True
        # try to localize only naive
        def localize_try(ts):
            if pd.isna(ts):
                return pd.NaT
            if ts.tzinfo is None:
                try:
                    return ts.replace(tzinfo=KST)
                except Exception:
                    return ts
            return ts
        df["timestamp"] = df["timestamp"].apply(localize_try)
        df = df[pd.notna(df["timestamp"])]
    return df

def checkin_stats(df: pd.DataFrame, lookback_days=30):
    df = ensure_timestamp(df.copy())
    if df.empty:
        return {"missing_days": [], "z_outliers_idx": [], "mean_min": None, "std_min": None}
    df_recent = df[df["timestamp"] >= (now_kst() - timedelta(days=lookback_days))]
    if df_recent.empty:
        return {"missing_days": [], "z_outliers_idx": [], "mean_min": None, "std_min": None}
    daily = (df_recent
             .assign(date=lambda x: x["timestamp"].dt.date,
                     minutes=lambda x: x["timestamp"].dt.hour*60 + x["timestamp"].dt.minute)
             .sort_values("timestamp")
             .groupby("date", as_index=False).first())
    days = [(now_kst().date() - timedelta(days=i)) for i in range(lookback_days)]
    existing = set(daily["date"].tolist())
    missing = [d for d in days if d not in existing]
    if len(daily) >= 5:
        mins = daily["minutes"].to_numpy()
        mu = float(np.mean(mins))
        sd = float(np.std(mins)) if np.std(mins) > 0 else 1.0
        zscores = (mins - mu) / sd
        out_idx = list(np.where(np.abs(zscores) > 2)[0])
        return {"missing_days": missing, "z_outliers_idx": out_idx, "mean_min": mu, "std_min": sd, "daily": daily}
    return {"missing_days": missing, "z_outliers_idx": [], "mean_min": None, "std_min": None, "daily": daily}

def enumerate_due_times(start_clock: dtime, interval_hours: int, from_dt: datetime, to_dt: datetime):
    start_at = datetime.combine(from_dt.date(), start_clock, tzinfo=KST)
    while start_at > from_dt:
        start_at -= timedelta(hours=interval_hours)
    while start_at + timedelta(hours=interval_hours) < from_dt:
        start_at += timedelta(hours=interval_hours)
    times, cur = [], start_at
    while cur <= to_dt:
        if cur >= from_dt: times.append(cur)
        cur += timedelta(hours=interval_hours)
    return times

def estimate_adherence(meds_df, med_log_df, days=7, window_minutes=60):
    to_dt = now_kst(); from_dt = to_dt - timedelta(days=days)
    due_list = []
    taken_list = med_log_df[(pd.to_datetime(med_log_df["taken_at"])>=from_dt) & (pd.to_datetime(med_log_df["taken_at"])<=to_dt)].copy()
    for _, row in meds_df.iterrows():
        name = row["name"]; iv = int(row["interval_hours"]); sc = parse_time_str(str(row["start_time"]))
        if not sc: continue
        for d in enumerate_due_times(sc, iv, from_dt, to_dt):
            due_list.append({"name": name, "due_time": d})
    due_df = pd.DataFrame(due_list)
    if due_df.empty: return 0, 0
    taken_on_time, window = 0, timedelta(minutes=window_minutes)
    for _, due in due_df.iterrows():
        name = due["name"]; dtime_ = due["due_time"]
        cand = taken_list[(taken_list["name"]==name) & (pd.to_datetime(taken_list["taken_at"]).between(dtime_-window, dtime_+window))]
        if len(cand):
            taken_on_time += 1
            taken_list = taken_list.drop(cand.index[0])
    return len(due_df), taken_on_time

def already_taken(med_log_df, name, due_time, window_minutes=60):
    w = timedelta(minutes=window_minutes)
    hit = med_log_df[(med_log_df["name"]==name) & (pd.to_datetime(med_log_df["taken_at"]).between(due_time-w, due_time+w))]
    return len(hit) > 0

def due_now_list(meds_df, med_log_df, within_minutes=15, overdue_minutes=90):
    now = now_kst(); due_items = []
    for _, row in meds_df.iterrows():
        name = row["name"]; iv = int(row["interval_hours"]); sc = parse_time_str(str(row["start_time"]))
        if not sc: continue
        dues = enumerate_due_times(sc, iv, now - timedelta(days=2), now + timedelta(days=1))
        if not dues: continue
        closest = min(dues, key=lambda d: abs((d - now).total_seconds()))
        diff_min = (closest - now).total_seconds()/60.0
        status = None
        if abs(diff_min) <= within_minutes:
            status = "due"
        elif diff_min < 0 and abs(diff_min) <= overdue_minutes:
            status = "overdue"
        if status and not already_taken(med_log_df, name, closest, window_minutes=60):
            due_items.append({"name": name, "due_time": closest, "status": status})
    return due_items

def risk_score(checkins_df, med_log_df, meds_df):
    cs = checkin_stats(checkins_df, lookback_days=14)
    missing_last3 = [d for d in cs.get("missing_days", []) if (now_kst().date() - d).days <= 3]
    n_missing3 = len(missing_last3); n_out7 = 0
    if "daily" in cs and len(cs["daily"])>0 and cs.get("mean_min") is not None and cs.get("std_min",0)>0:
        last7 = cs["daily"][cs["daily"]["date"] >= (now_kst().date()-timedelta(days=7))]
        if len(last7) >= 5:
            mins = last7["minutes"].to_numpy()
            z = (mins - cs["mean_min"]) / cs["std_min"]
            n_out7 = int(np.sum(np.abs(z)>2))
    adherence = 1.0
    if not meds_df.empty:
        due_total, taken_on_time = estimate_adherence(meds_df, med_log_df, days=7, window_minutes=60)
        adherence = (taken_on_time / due_total) if due_total>0 else 1.0
    score = min(n_missing3, 3)/3*40 + min(n_out7, 5)/5*20 + (1.0 - adherence)*40
    return round(max(0, min(100, score)), 1), {
        "missing_last3": n_missing3, "outliers_last7": n_out7, "adherence_7d": round(adherence*100,1)
    }

# ------------------------
# 초기 파일 생성 / 로드
# ------------------------
ensure_csv(CHECKIN_CSV, ["timestamp","lat","lon"])
ensure_csv(MEDS_CSV, ["name","interval_hours","start_time","notes"])
ensure_csv(MEDLOG_CSV, ["name","due_time","taken_at"])
ensure_csv(INSTITUTIONS_CSV, [])
ensure_csv(REGIONAL_CSV, [])

checkins = pd.read_csv(CHECKIN_CSV) if os.path.exists(CHECKIN_CSV) else pd.DataFrame(columns=["timestamp","lat","lon"])
checkins = ensure_timestamp(checkins)

meds = pd.read_csv(MEDS_CSV) if os.path.exists(MEDS_CSV) else pd.DataFrame(columns=["name","interval_hours","start_time","notes"])
med_log = pd.read_csv(MEDLOG_CSV) if os.path.exists(MEDLOG_CSV) else pd.DataFrame(columns=["name","due_time","taken_at"])
if "taken_at" in med_log.columns:
    med_log["taken_at"] = pd.to_datetime(med_log["taken_at"], errors="coerce").dropna()

try:
    institutions = safe_read_csv(INSTITUTIONS_CSV) if os.path.exists(INSTITUTIONS_CSV) else pd.DataFrame()
except Exception:
    institutions = pd.DataFrame()
try:
    regional = safe_read_csv(REGIONAL_CSV) if os.path.exists(REGIONAL_CSV) else pd.DataFrame()
except Exception:
    regional = pd.DataFrame()

# ------------------------
# UI 기본 설정 (글자 크기)
# ------------------------
st.set_page_config(page_title="🧡 독거노인 지원 웹앱 (Prototype)", page_icon="🧡", layout="wide")
font_choice = st.sidebar.selectbox("글자 크기", ["소","일반","대형","초대형"], index=1)
_font_map = {"소":"16px","일반":"20px","대형":"24px","초대형":"30px"}
base_font = _font_map.get(font_choice, "20px")
st.markdown(f"""
<style>
:root {{ --base-font: {base_font}; }}
html, body, [class*="css"]  {{ font-size: var(--base-font); }}
button, .stButton>button {{ font-size: 1.05rem !important; padding: 0.5rem 0.9rem !important; border-radius: 10px !important; }}
.dog-img {{ width:260px; height:260px; border-radius:14px; cursor:pointer; }}
</style>
""", unsafe_allow_html=True)

st.title("🧡 독거노인 지원 웹앱 (nurinuri_not_alone)")

# ------------------------
# 탭 (5개)
# ------------------------
tab1, tab2, tab3, tab4, tab5 = st.tabs(["① 체크인(강아지)","② 위험도/119 시나리오","③ 복약 스케줄러","④ 주변 의료기관 찾기","⑤ 데이터/설정"])

# ------------------------
# ① 체크인 (강아지 클릭)
# ------------------------
with tab1:
    st.header("① 매일 체크인 (강아지 터치)")
    st.markdown("강아지를 터치하면 체크인됩니다. (위치 허용 시 날씨를 표시합니다.)")

    # custom HTML component for dog image + geolocation
    dog_html = f"""
    <div style="text-align:center;">
      <img id="nuri_dog" src="{DOG_URL_IDLE}" class="dog-img" />
      <div style="font-size:14px;margin-top:8px;">강아지를 터치하세요 🐶</div>
      <script>
        const send = v => window.parent.postMessage({{type:"streamlit:setComponentValue", value:v}}, "*");
        const dog = document.getElementById("nuri_dog");
        dog.onclick = () => {{
          // visual feedback
          dog.style.transform = "scale(1.06) rotate(4deg)";
          setTimeout(()=>dog.style.transform="", 220);
          // try geolocation
          if (navigator.geolocation) {{
            navigator.geolocation.getCurrentPosition(function(pos){{
              send({{action:"checkin", lat: pos.coords.latitude, lon: pos.coords.longitude, ts: new Date().toISOString(), clicked:true}});
            }}, function(err){{
              send({{action:"checkin", lat:null, lon:null, ts: new Date().toISOString(), clicked:true}});
            }}, {{timeout:7000}});
          }} else {{
            send({{action:"checkin", lat:null, lon:null, ts: new Date().toISOString(), clicked:true}});
          }}
        }};
      </script>
    </div>
    """
    from streamlit.components.v1 import html as st_html
    comp_res = st_html(dog_html, height=380)

    # when JS posts, streamlit's component returns the posted dict as comp_res
    if comp_res is not None:
        if isinstance(comp_res, dict) and comp_res.get("action") == "checkin":
            lat = comp_res.get("lat"); lon = comp_res.get("lon")
            ts_raw = comp_res.get("ts")
            try:
                ts = pd.to_datetime(ts_raw)
                # localize if naive
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=KST)
            except Exception:
                ts = now_kst()
            new = {"timestamp": ts, "lat": lat, "lon": lon}
            checkins = pd.concat([checkins, pd.DataFrame([new])], ignore_index=True)
            checkins["timestamp"] = pd.to_datetime(checkins["timestamp"], errors="coerce")
            save_csv(checkins, CHECKIN_CSV)
            # show success and weather via Open-Meteo if lat/lon present
            st.success(f"체크인 완료: {ts.astimezone(KST).strftime('%Y-%m-%d %H:%M:%S')}")
            if lat is not None and lon is not None:
                # Open-Meteo API (no key) - current weather
                try:
                    om_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&timezone=Asia%2FSeoul"
                    r = requests.get(om_url, timeout=6)
                    j = r.json()
                    cw = j.get("current_weather", {})
                    temp = cw.get("temperature")
                    wind = cw.get("winddirection")
                    weather_text = f"현재 기온 {temp}°C"
                    st.info(f"현재 위치 날씨: {weather_text}")
                except Exception as e:
                    st.info("날씨 정보를 가져오지 못했습니다.")
            else:
                st.info("위치 정보 미허용: 수동 위치 설정 또는 집 위치 사용 가능.")

    # recent checkins and hourly plot
    st.markdown("---")
    st.subheader("최근 체크인 기록 및 시간(시간 단위)")
    if not checkins.empty:
        dfc = checkins.copy()
        dfc["timestamp"] = pd.to_datetime(dfc["timestamp"], errors="coerce")
        st.dataframe(dfc.sort_values("timestamp", ascending=False).head(50), use_container_width=True)
        df_plot = (dfc.assign(date=lambda x: pd.to_datetime(x["timestamp"]).dt.date,
                              hour_float=lambda x: pd.to_datetime(x["timestamp"]).dt.hour + pd.to_datetime(x["timestamp"]).dt.minute/60)
                        .sort_values("timestamp")
                        .groupby("date", as_index=False)["hour_float"].min()
                        .sort_values("date"))
        st.caption("날짜별 첫 체크인 시각 (시간 단위, 소수점은 분 비율)")
        if not df_plot.empty:
            st.line_chart(df_plot.set_index("date")["hour_float"])
    else:
        st.info("아직 체크인 기록이 없습니다.")

# ------------------------
# ② 위험도/119 시나리오
# ------------------------
with tab2:
    st.header("② 위험도 예측 및 자동 알림(시뮬레이션)")
    leftc, rightc = st.columns([1,3])
    with leftc:
        risk_thr = st.slider("119/보호자 연락(가상) 발동 기준(%)", 10, 100, 60, 5)
        if st.button("🔔 테스트 알림음 재생"):
            # play test alarm (user gesture)
            st.markdown(f'<audio autoplay controls src="data:audio/wav;base64,{ALARM_B64}"></audio>', unsafe_allow_html=True)
    with rightc:
        st.info("위험도는 최근 체크인/복약 이력 기반으로 계산됩니다. 임계치 초과 시 가상 경보가 실행됩니다.")

    score, detail = risk_score(checkins, med_log, meds)
    st.subheader(f"현재 위험도: {score}%")
    st.progress(min(1.0, score/100.0))
    c1,c2,c3 = st.columns(3)
    c1.metric("최근 3일 결측(일)", detail["missing_last3"])
    c2.metric("최근 7일 이상치(일)", detail["outliers_last7"])
    c3.metric("복약 준수(7일)", f"{detail['adherence_7d']}%")

    if score >= risk_thr:
        st.error("⚠️ 위험도 임계치 초과! (가상 경보/연락 시나리오)")
        # Try playing audio via autoplay HTML (may be blocked by browser)
        st.markdown(f'<audio autoplay controls src="data:audio/wav;base64,{ALARM_B64}"></audio>', unsafe_allow_html=True)
        st.markdown("""
**시뮬레이션: 자동 연락 절차**
1) 보호자 1차 연락 시도  
2) 미응답 시 119 연계 안내 음성 송출  
3) 위치/최근 체크인/복약정보 요약 전송(가상)
""")
    else:
        st.success("현재는 임계치 미만입니다.")

# ------------------------
# ③ 복약 스케줄러 / 리마인더
# ------------------------
with tab3:
    st.header("③ 복약 스케줄러 / 리마인더")
    st.caption("앱이 열려 있을 때에만 리마인더가 화면에 표시됩니다(프로토타입).")

    with st.form("add_med", clear_on_submit=True):
        st.subheader("약 추가")
        cx, cy, cz = st.columns([2,1,2])
        name = cx.text_input("약 이름", placeholder="예: Warfarin")
        interval = cy.number_input("복용 간격(시간)", 1, 48, 12, 1)
        start_t = cz.text_input("첫 복용 시각(HH:MM)", "08:00")
        notes = st.text_input("메모(선택)", "")
        submit = st.form_submit_button("추가")
        if submit:
            if name and parse_time_str(start_t):
                meds = pd.concat([meds, pd.DataFrame([{"name": name, "interval_hours": int(interval), "start_time": start_t, "notes": notes}])], ignore_index=True)
                save_csv(meds, MEDS_CSV)
                st.success(f"약 추가됨: {name}")
                st.experimental_rerun()
            else:
                st.error("입력을 확인하세요. (시각 형식 HH:MM)")

    if len(meds):
        st.subheader("등록된 약")
        st.dataframe(meds, use_container_width=True)
    else:
        st.info("등록된 약이 없습니다.")

    # due items
    due_items = due_now_list(meds, med_log, within_minutes=15, overdue_minutes=90)
    st.subheader("리마인더")
    if due_items:
        for idx, item in enumerate(due_items):
            name_i = item["name"]; due_dt = item["due_time"]
            due_txt = due_dt.astimezone(KST).strftime("%Y-%m-%d %H:%M")
            status = "🕒 곧 복약" if item["status"]=="due" else "⏰ 연체"
            st.warning(f"{status}: {name_i} / 예정시각 {due_txt}")
            b1,b2,_ = st.columns([1,1,3])
            with b1:
                if st.button(f"✅ {name_i} 복용 기록", key=f"take_{idx}"):
                    med_log = pd.concat([med_log, pd.DataFrame([{"name": name_i, "due_time": due_dt, "taken_at": now_kst()}])], ignore_index=True)
                    save_csv(med_log, MEDLOG_CSV)
                    st.success(f"{name_i} 복용 기록 완료")
                    st.experimental_rerun()
            with b2:
                # attempt to play audio (user gesture recommended)
                st.markdown(f'<audio autoplay controls src="data:audio/wav;base64,{ALARM_B64}"></audio>', unsafe_allow_html=True)
            # show interactions
            inters = lookup_interactions(name_i)
            if inters:
                st.info("복용 관련 주의사항:")
                for w in inters:
                    st.write(f"- {w}")
    else:
        st.success("현재 15분 이내 예정/연체 항목 없음")

    st.markdown("---")
    st.subheader("복용 기록")
    if not med_log.empty:
        st.dataframe(med_log.sort_values("taken_at", ascending=False).head(200), use_container_width=True)
    else:
        st.info("복용 기록 없음")

# ------------------------
# ④ 주변 의료기관 찾기 및 추천 (전국 지원)
# ------------------------
with tab4:
    st.header("④ 주변 약국/병원 찾기 및 추천 (전국 CSV 지원)")
    st.caption("전국 의료기관 CSV를 업로드하면 lat/lon 컬럼을 찾아 반경 내 기관을 추천합니다.")

    inst_file = st.file_uploader("전국 의료기관 표준데이터 CSV 업로드", type=["csv"])
    if inst_file is not None:
        try:
            raw = safe_read_csv(inst_file)
            # normalize columns
            lat_col = None; lon_col = None
            for c in raw.columns:
                lc = c.lower()
                if lat_col is None and any(k in lc for k in ["위도","lat","latitude","y","좌표y"]): lat_col = c
                if lon_col is None and any(k in lc for k in ["경도","lon","lng","longitude","x","좌표x"]): lon_col = c
            if lat_col and lon_col:
                raw = raw.rename(columns={lat_col:"lat", lon_col:"lon"})
                raw["lat"] = pd.to_numeric(raw["lat"], errors="coerce"); raw["lon"] = pd.to_numeric(raw["lon"], errors="coerce")
                # name col
                name_col = None
                for c in raw.columns:
                    if any(k in c.lower() for k in ["명","name","기관","병원","약국"]):
                        name_col = c; break
                if name_col: raw = raw.rename(columns={name_col:"name"})
                if "type" not in raw.columns:
                    raw["type"] = "병원"
                institutions = raw[[c for c in ["name","type","lat","lon","address"] if c in raw.columns]].copy()
                save_csv(institutions, INSTITUTIONS_CSV)
                st.success(f"업로드 완료: {len(institutions)}개 기관 저장")
            else:
                st.error("CSV에서 위도(lat)/경도(lon) 컬럼을 찾을 수 없습니다.")
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")

    # home location usage
    st.subheader("검색 위치 설정")
    home = load_home()
    use_home = st.checkbox("저장된 집 위치 사용", value=(home is not None))
    if use_home and home is not None:
        lat = float(home["lat"]); lon = float(home["lon"])
        st.success(f"집 위치: {home['label']} ({lat:.6f}, {lon:.6f})")
        if st.button("집 위치 삭제"):
            try:
                os.remove(HOME_JSON)
            except Exception:
                pass
            st.experimental_rerun()
    else:
        lat = st.number_input("위도(lat)", value=37.5665, format="%.6f")
        lon = st.number_input("경도(lon)", value=126.9780, format="%.6f")
        if st.button("이 위치를 집으로 저장"):
            if save_home(lat, lon, "우리 집"):
                st.success("집 위치 저장됨")
                st.experimental_rerun()

    if not institutions.empty and {"lat","lon"}.issubset(institutions.columns):
        radius_km = st.slider("검색 반경(km)", 1, 100, 10)
        tsel = st.selectbox("기관 유형", ["전체","병원","약국"], index=0)
        df = institutions.copy()
        if tsel != "전체":
            df = df[df["type"].str.contains(tsel, na=False)]
        df["distance_km"] = haversine_km(lat, lon, df["lat"].astype(float), df["lon"].astype(float))
        df = df[df["distance_km"] <= radius_km].sort_values("distance_km").reset_index(drop=True)
        if len(df):
            st.subheader("가까운 순 추천 리스트")
            show_cols = [c for c in ["name","type","address","distance_km"] if c in df.columns]
            st.dataframe(df[show_cols].head(50), use_container_width=True)
            layers = [
                pdk.Layer("ScatterplotLayer", data=pd.DataFrame([{"name":"집","lat":lat,"lon":lon}]), get_position='[lon, lat]', get_radius=120, get_fill_color=[255,0,0,200]),
                pdk.Layer("ScatterplotLayer", data=df.head(200), get_position='[lon, lat]', get_radius=60, get_fill_color=[0,128,255,160])
            ]
            view_state = pdk.ViewState(latitude=lat, longitude=lon, zoom=11)
            st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view_state))
        else:
            st.info("반경 내 결과 없음.")
    else:
        st.info("의료기관 데이터가 없습니다. CSV 업로드 후 시도하세요.")

# ------------------------
# ⑤ 데이터/설정 (다운로드/업로드 + 위험도 점수식 설명)
# ------------------------
with tab5:
    st.header("⑤ 데이터/설정 (자료 관리)")
    c1,c2,c3,c4 = st.columns(4)
    with c1:
        st.download_button("체크인 CSV", data=checkins.to_csv(index=False).encode("utf-8"), file_name="checkins.csv")
    with c2:
        st.download_button("약 목록 CSV", data=meds.to_csv(index=False).encode("utf-8"), file_name="meds.csv")
    with c3:
        st.download_button("복약 기록 CSV", data=med_log.to_csv(index=False).encode("utf-8"), file_name="med_log.csv")
    with c4:
        if not institutions.empty:
            st.download_button("의료기관 CSV", data=institutions.to_csv(index=False).encode("utf-8"), file_name="institutions.csv")
        else:
            st.write("의료기관 CSV: (없음)")

    st.markdown("---")
    st.markdown("#### 자동 로드 상태 미리보기")
    if os.path.exists("/mnt/data/전국의료기관 표준데이터.csv") or os.path.exists("전국의료기관 표준데이터.csv"):
        st.success("전국의료기관 원본 감지됨(자동 변환 가능)")
    if not institutions.empty:
        st.dataframe(institutions.head(10), use_container_width=True)
    else:
        st.info("의료기관 데이터 없음")

    st.markdown("#### 위험도 계산식(요약)")
    st.code("""
# score = 0
# score += min(n_missing3, 3) / 3 * 40      # 최근 3일 결측
# score += min(n_out7, 5) / 5 * 20          # 최근 7일 이상치(체크인 시각)
# score += (1.0 - adherence) * 40           # 7일 복약 준수율 역가중
# => 0~100 점수
""", language="python")

# ------------------------
# 상태 저장 (앱 종료시)
# ------------------------
try:
    save_csv(checkins, CHECKIN_CSV)
    save_csv(meds, MEDS_CSV)
    save_csv(med_log, MEDLOG_CSV)
    if not institutions.empty: save_csv(institutions, INSTITUTIONS_CSV)
    if not regional.empty: save_csv(regional, REGIONAL_CSV)
except Exception:
    pass
