import time
import re
import streamlit as st
import pandas as pd
import requests
import plotly.express as px
import plotly.graph_objects as go

# 1. 페이지 기본 설정
st.set_page_config(
    page_title="도서 대출 베스트셀러 트렌드 분석 (team12)",
    page_icon="📚",
    layout="wide"
)

# KDC 10대 주제 매핑
KDC_TOPICS = {
    "0": "0: 총류",
    "1": "1: 철학",
    "2": "2: 종교",
    "3": "3: 사회과학",
    "4": "4: 자연과학",
    "5": "5: 기술과학",
    "6": "6: 예술",
    "7": "7: 언어",
    "8": "8: 문학",
    "9": "9: 역사",
}

LIST_TOPIC_OPTIONS = {"ALL": "전체 주제 (종합)"}
LIST_TOPIC_OPTIONS.update(KDC_TOPICS)

# ---------------------------------------------------------
# 세션 상태 초기화 (동시 작동 충돌 방지용)
# ---------------------------------------------------------
DEFAULT_STATE = {
    "active_mode": None,   # None | "trend" | "list"
    "trend_years": [],
    "trend_topics": [],
    "trend_top_n": None,
    "list_year": None,
    "list_topic": None,
    "list_top_n": None,
}
for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


def on_trend_change():
    """왼쪽 사이드바(트렌드 분석) 조작 시 오른쪽 기능 잠금 및 초기화"""
    has_input = (
        bool(st.session_state.trend_years)
        or bool(st.session_state.trend_topics)
        or (st.session_state.trend_top_n is not None)
    )
    if has_input:
        st.session_state.active_mode = "trend"
        st.session_state.list_year = None
        st.session_state.list_topic = None
        st.session_state.list_top_n = None
    else:
        st.session_state.active_mode = None


def on_list_change():
    """오른쪽 사이드바(베스트셀러 리스트) 조작 시 왼쪽 기능 잠금 및 초기화"""
    has_input = (
        (st.session_state.list_year is not None)
        or (st.session_state.list_topic is not None)
        or (st.session_state.list_top_n is not None)
    )
    if has_input:
        st.session_state.active_mode = "list"
        st.session_state.trend_years = []
        st.session_state.trend_topics = []
        st.session_state.trend_top_n = None
    else:
        st.session_state.active_mode = None


def reset_all_modes():
    """모든 선택 조건 및 모드 잠금 해제"""
    st.session_state.active_mode = None
    st.session_state.trend_years = []
    st.session_state.trend_topics = []
    st.session_state.trend_top_n = None
    st.session_state.list_year = None
    st.session_state.list_topic = None
    st.session_state.list_top_n = None


# ---------------------------------------------------------
# 유틸리티 및 API 조회 함수
# ---------------------------------------------------------
def get_api_key() -> str:
    """st.secrets에서 API 키를 안전하게 불러옵니다."""
    try:
        for key_name in ["DATA4LIBRARY_KEY", "API_KEY", "authKey", "data4library_key"]:
            if key_name in st.secrets:
                return str(st.secrets[key_name]).strip()
    except Exception:
        pass
    return ""


def parse_main_topic(class_no: str) -> str:
    if class_no and class_no[0] in KDC_TOPICS:
        return KDC_TOPICS[class_no[0]]
    return "기타/미분류"


def parse_sub_topic(class_nm: str, main_topic: str) -> str:
    if class_nm and ">" in class_nm:
        parts = [p.strip() for p in class_nm.split(">") if p.strip()]
        if len(parts) >= 2:
            return f"{parts[-2]} > {parts[-1]}"
        return parts[-1]
    elif class_nm:
        return class_nm.strip()
    return main_topic


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_bestsellers(api_key: str, year: int, top_n: int, kdc_code: str = "ALL") -> pd.DataFrame:
    """도서 정보나루 API에서 특정 연도(및 선택적 KDC 주제)의 상위 N위 인기대출도서를 조회합니다."""
    url = "http://data4library.kr/api/loanItemSrch"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    page_size = min(top_n, 50)
    total_pages = (top_n + page_size - 1) // page_size
    rows = []

    for page_no in range(1, total_pages + 1):
        params = {
            "authKey": api_key.strip(),
            "startDt": f"{year}-01-01",
            "endDt": f"{year}-12-31",
            "pageNo": page_no,
            "pageSize": page_size,
            "format": "json",
        }
        if kdc_code and kdc_code != "ALL":
            params["kdc"] = kdc_code

        raw_text = ""
        response = None
        last_err = None

        for attempt in range(3):
            try:
                with requests.Session() as session:
                    response = session.get(url, params=params, headers=headers, timeout=(10, 25))
                    response.raise_for_status()
                    raw_text = response.text.strip()
                if raw_text.startswith("{"):
                    break
            except requests.exceptions.RequestException as e:
                last_err = e
            time.sleep(3.0 * (attempt + 1))
        else:
            if last_err is not None and not raw_text:
                raise ValueError(f"{year}년 데이터 요청 시간이 초과되었습니다. 잠시 후 다시 시도해 주세요.")

        if not raw_text:
            raise ValueError(f"{year}년 조회 시 API 서버가 빈 응답을 반환했습니다. 잠시 후 다시 시도해 주세요.")

        if not raw_text.startswith("{"):
            err_match = re.search(r"<error>(.*?)</error>", raw_text)
            err_msg = err_match.group(1) if err_match else raw_text[:200]
            raise ValueError(f"API 서버 안내 메시지 ({year}년): {err_msg}")

        data = response.json()
        docs = data.get("response", {}).get("docs", [])
        if isinstance(docs, dict):
            docs = [docs]

        for item in docs:
            if len(rows) >= top_n:
                break
            doc = item.get("doc", {})
            class_no = str(doc.get("class_no", "")).strip()
            class_nm = str(doc.get("class_nm", "")).strip()
            main_topic = parse_main_topic(class_no)
            sub_topic = parse_sub_topic(class_nm, main_topic)

            try:
                rank = int(doc.get("ranking", len(rows) + 1))
            except ValueError:
                rank = len(rows) + 1

            try:
                loan_cnt = int(str(doc.get("loan_count", "0")).replace(",", ""))
            except ValueError:
                loan_cnt = 0

            rows.append({
                "연도": int(year),
                "순위": rank,
                "대주제": main_topic,
                "세부주제": sub_topic,
                "분류전체": class_nm if class_nm else main_topic,
                "KDC코드": class_no,
                "도서명": str(doc.get("bookname", "")).strip(),
                "저자": str(doc.get("authors", "")).strip(),
                "출판사": str(doc.get("publisher", "")).strip(),
                "출판년도": str(doc.get("publication_year", "")).strip(),
                "대출건수": loan_cnt,
            })

        if page_no < total_pages:
            time.sleep(2.0)

    return pd.DataFrame(rows)


# =========================================================
# 왼쪽 사이드바: 기능 A - 연도별 트렌드 & 교체 주기 분석
# =========================================================
st.sidebar.header("📊 [기능 1] 트렌드 분석 조건")
st.sidebar.caption("전체 신규 주제 진입률과 선택 주제 내 최다 대출건수·순위 변화를 분석합니다.")

api_key = get_api_key()
if not api_key:
    api_key = st.sidebar.text_input(
        "도서 정보나루 API 인증키",
        type="password",
        help=".streamlit/secrets.toml에 키가 없는 경우 직접 입력하세요."
    )

trend_disabled = (st.session_state.active_mode == "list")

if trend_disabled:
    st.sidebar.warning("🔒 오른쪽 사이드바의 **[베스트셀러 리스트 조회]**가 작동 중입니다. 충돌 방지를 위해 현재 기능이 잠겼습니다.")
    st.sidebar.button(
        "🔄 초기화 후 트렌드 분석 사용하기",
        on_click=reset_all_modes,
        use_container_width=True,
        key="reset_from_left"
    )

st.sidebar.multiselect(
    "1. 조회 연도 선택 (복수 선택)",
    options=list(range(2016, 2027)),
    placeholder="연도를 선택하세요 (2개 이상)",
    key="trend_years",
    on_change=on_trend_change,
    disabled=trend_disabled,
)

st.sidebar.multiselect(
    "2. 관심 주제 선택 (KDC 대분류)",
    options=list(KDC_TOPICS.keys()),
    placeholder="관심 주제를 선택하세요",
    format_func=lambda k: KDC_TOPICS[k],
    key="trend_topics",
    on_change=on_trend_change,
    disabled=trend_disabled,
)

st.sidebar.selectbox(
    "3. 베스트셀러 상위 순위 기준",
    options=[10, 20, 30, 50, 100],
    placeholder="상위 순위 기준을 선택하세요",
    format_func=lambda x: f"상위 {x}위 (Top {x})",
    key="trend_top_n",
    on_change=on_trend_change,
    disabled=trend_disabled,
)

if st.session_state.active_mode == "trend":
    st.sidebar.button(
        "🗑️ 선택 조건 전체 초기화",
        on_click=reset_all_modes,
        use_container_width=True,
        key="clear_trend_btn"
    )

st.sidebar.markdown("---")
st.sidebar.caption("데이터 출처: 국립중앙도서관 도서 정보나루 (loanItemSrch)")


# =========================================================
# 메인 화면 분할: 중앙 결과 화면 + 오른쪽 사이드바(기능 B)
# =========================================================
center_col, right_sidebar = st.columns([3.0, 1.35], gap="large")

# ---------------------------------------------------------
# 오른쪽 사이드바: 기능 B - 단일 연도 베스트셀러 리스트 조회
# ---------------------------------------------------------
with right_sidebar:
    with st.container(border=True):
        st.subheader("📋 [기능 2] 베스트셀러 리스트")
        st.caption("특정 연도와 주제의 베스트셀러 도서 순위표를 조회합니다.")

        list_disabled = (st.session_state.active_mode == "trend")

        if list_disabled:
            st.warning("🔒 왼쪽 사이드바의 **[트렌드 분석]**이 작동 중입니다. 충돌 방지를 위해 현재 기능이 잠겼습니다.")
            st.button(
                "🔄 초기화 후 리스트 조회 사용하기",
                on_click=reset_all_modes,
                use_container_width=True,
                key="reset_from_right"
            )

        st.selectbox(
            "1. 조회 연도 (단일 선택)",
            options=list(range(2016, 2027)),
            placeholder="조회할 연도를 선택하세요",
            key="list_year",
            on_change=on_list_change,
            disabled=list_disabled,
        )

        st.selectbox(
            "2. 주제 분류 (KDC 대분류)",
            options=list(LIST_TOPIC_OPTIONS.keys()),
            placeholder="주제를 선택하세요",
            format_func=lambda k: LIST_TOPIC_OPTIONS[k],
            key="list_topic",
            on_change=on_list_change,
            disabled=list_disabled,
        )

        st.selectbox(
            "3. 상위 순위 기준",
            options=[10, 20, 30, 50, 100],
            placeholder="상위 순위를 선택하세요",
            format_func=lambda x: f"상위 {x}위 (Top {x})",
            key="list_top_n",
            on_change=on_list_change,
            disabled=list_disabled,
        )

        if st.session_state.active_mode == "list":
            st.button(
                "🗑️ 리스트 조건 초기화",
                on_click=reset_all_modes,
                use_container_width=True,
                key="clear_list_btn"
            )


# ---------------------------------------------------------
# 중앙 메인 화면: 선택된 모드에 따른 분석 결과 또는 리스트 출력
# ---------------------------------------------------------
with center_col:
    st.title("📚 도서 대출 베스트셀러 트렌드 분석 (team12)")

    if not api_key:
        st.warning("API 인증키가 설정되지 않았습니다. `.streamlit/secrets.toml`을 확인하거나 왼쪽 사이드바에 키를 입력해 주세요.")
        st.stop()

    # [초기 대기 상태]
    if st.session_state.active_mode is None:
        st.info(
            "원하시는 분석 기능을 선택해 주세요. (두 기능은 충돌 방지를 위해 동시에 실행되지 않습니다.)\n\n"
            "- **👈 왼쪽 사이드바 ([기능 1] 트렌드 분석):** 전체 베스트셀러 신규 주제 진입률·교체 주기 및 선택 주제 내 최다 대출건수·순위 변화 분석\n"
            "- **👉 오른쪽 사이드바 ([기능 2] 베스트셀러 리스트):** 특정 연도·주제의 인기대출도서 순위 리스트 조회"
        )
        st.stop()

    # =====================================================
    # 모드 1: 왼쪽 사이드바 - 연도별 트렌드 분석 실행
    # =====================================================
    if st.session_state.active_mode == "trend":
        selected_years = st.session_state.trend_years
        selected_kdc_keys = st.session_state.trend_topics
        top_n = st.session_state.trend_top_n

        if not selected_years or not selected_kdc_keys or top_n is None:
            st.info("👈 왼쪽 사이드바에서 **조회 연도(2개 이상)**, **관심 주제**, **상위 순위 기준**을 모두 선택하면 분석 그래프가 나타납니다.")
            st.stop()

        if len(selected_years) < 2:
            st.warning("연도별 추이 및 신규 주제 진입 비율을 계산하려면 **조회 연도를 2개 이상** 선택해 주세요.")
            st.stop()

        years_sorted = sorted(selected_years)
        selected_topic_labels = [KDC_TOPICS[k] for k in selected_kdc_keys]

        all_dfs = []
        progress_bar = st.progress(0, text="연도별 베스트셀러 데이터를 불러오는 중입니다...")

        try:
            for idx, yr in enumerate(years_sorted):
                df_yr = fetch_bestsellers(api_key, yr, top_n, kdc_code="ALL")
                all_dfs.append(df_yr)
                progress_bar.progress((idx + 1) / len(years_sorted), text=f"{yr}년 데이터 수집 완료 ({idx + 1}/{len(years_sorted)})")
                if idx < len(years_sorted) - 1:
                    time.sleep(2.0)
        except Exception as e:
            st.error(f"데이터 수집 중 오류가 발생했습니다: {e}")
            st.button("🔄 다시 시도하기", on_click=st.rerun)
            st.stop()
        finally:
            progress_bar.empty()

        df_all = pd.concat(all_dfs, ignore_index=True)

        if df_all.empty:
            st.error("조회된 도서 데이터가 없습니다. API 인증키 상태나 조회 연도를 확인해 주세요.")
            st.stop()

        # -------------------------------------------------
        # [연구 질문 1] 전체 베스트셀러 기준 신규 주제 진입 비율 & 교체 주기
        # -------------------------------------------------
        turnover_records = []
        for i, yr in enumerate(years_sorted):
            curr_topics = set(df_all[df_all["연도"] == yr]["세부주제"].unique())
            total_cnt = len(curr_topics)

            if i == 0:
                turnover_records.append({
                    "연도": str(yr),
                    "전체_세부주제수": total_cnt,
                    "신규_주제수": total_cnt,
                    "유지_주제수": 0,
                    "신규진입비율(%)": None,
                    "기존유지비율(%)": None,
                    "신규진입_주제목록": ", ".join(sorted(curr_topics))
                })
            else:
                prev_yr = years_sorted[i - 1]
                prev_topics = set(df_all[df_all["연도"] == prev_yr]["세부주제"].unique())
                new_topics = curr_topics - prev_topics
                retained_topics = curr_topics & prev_topics

                new_ratio = round((len(new_topics) / total_cnt * 100), 1) if total_cnt > 0 else 0.0
                retained_ratio = round(100.0 - new_ratio, 1)

                turnover_records.append({
                    "연도": str(yr),
                    "전체_세부주제수": total_cnt,
                    "신규_주제수": len(new_topics),
                    "유지_주제수": len(retained_topics),
                    "신규진입비율(%)": new_ratio,
                    "기존유지비율(%)": retained_ratio,
                    "신규진입_주제목록": ", ".join(sorted(new_topics)) if new_topics else "없음"
                })

        df_turnover = pd.DataFrame(turnover_records)
        valid_turnover = df_turnover.dropna(subset=["신규진입비율(%)"])
        avg_new_ratio = valid_turnover["신규진입비율(%)"].mean() if not valid_turnover.empty else 0.0
        turnover_cycle = (100.0 / avg_new_ratio) if avg_new_ratio > 0 else float("inf")

        # 선택된 관심 주제 필터링
        df_selected_raw = df_all[df_all["대주제"].isin(selected_topic_labels)].copy()
        selected_max_loan = int(df_selected_raw["대출건수"].max()) if not df_selected_raw.empty else 0
        selected_best_rank = int(df_selected_raw["순위"].min()) if not df_selected_raw.empty else None

        # 상단 KPI 카드
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("분석 기간 및 기준", f"{years_sorted[0]}~{years_sorted[-1]}년", f"매년 전체 Top {top_n}")
        col2.metric("전체 신규 주제 진입률", f"{avg_new_ratio:.1f}%", "전년 대비 신규 세부주제 비율")
        col3.metric(
            "독자 관심사 교체 주기",
            f"약 {turnover_cycle:.1f}년" if turnover_cycle != float("inf") else "교체 없음",
            "전체 주제 순환 평균 기간"
        )
        col4.metric(
            "선택 주제 최고 기록",
            f"{selected_max_loan:,}건" if selected_max_loan > 0 else "진입 없음",
            f"최고 {selected_best_rank}위" if selected_best_rank is not None else "선택 순위권 외"
        )

        st.markdown("---")

        # =====================================================
        # 섹션 1: 연구 질문 1 - 전체 베스트셀러 신규 주제 진입 비율 & 교체 주기
        # =====================================================
        st.subheader(f"1️⃣ 매년 전체 베스트셀러 Top {top_n} 내 '신규 주제' 진입 비율 및 관심사 교체 주기")
        st.caption(
            f"전체 베스트셀러 상위 {top_n}위 도서의 KDC 세부 주제를 전년도 목록과 비교하여 "
            "새롭게 진입한 주제의 비율과 독자 관심사 교체 주기를 전체 기준으로 집계합니다."
        )

        q1_col1, q1_col2 = st.columns([3, 2])

        with q1_col1:
            fig_turnover = go.Figure()
            fig_turnover.add_trace(go.Bar(
                x=valid_turnover["연도"],
                y=valid_turnover["신규진입비율(%)"],
                name="신규 진입 주제 (%)",
                marker_color="#FF6B6B",
                text=valid_turnover["신규진입비율(%)"].apply(lambda v: f"{v:.1f}%"),
                textposition="inside"
            ))
            fig_turnover.add_trace(go.Bar(
                x=valid_turnover["연도"],
                y=valid_turnover["기존유지비율(%)"],
                name="전년 유지 주제 (%)",
                marker_color="#4ECDC4",
                text=valid_turnover["기존유지비율(%)"].apply(lambda v: f"{v:.1f}%"),
                textposition="inside"
            ))
            fig_turnover.update_layout(
                barmode="stack",
                title=f"연도별 전체 베스트셀러 Top {top_n} 신규 진입 vs 기존 유지 주제 비율",
                xaxis_title="조회 연도",
                yaxis_title="주제 비율 (%)",
                yaxis=dict(range=[0, 105]),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                height=380
            )
            st.plotly_chart(fig_turnover, use_container_width=True)

        with q1_col2:
            st.markdown("#### 📊 전체 관심사 교체 주기 요약")
            st.info(
                f"- **연평균 신규 주제 진입률:** **{avg_new_ratio:.1f}%**\n"
                f"- **추정 관심사 교체 주기:** **약 {turnover_cycle:.1f}년**\n\n"
                f"매년 전체 상위 {top_n}위권 세부 주제의 약 **{avg_new_ratio:.1f}%**가 새로운 분야로 교체되며, "
                f"독자들의 주요 독서 관심사 판도가 완전히 한 바퀴 순환하는 데 평균 **약 {turnover_cycle:.1f}년**이 소요됩니다."
            )
            st.dataframe(
                valid_turnover[["연도", "전체_세부주제수", "신규_주제수", "유지_주제수", "신규진입비율(%)"]],
                use_container_width=True,
                hide_index=True
            )

        with st.expander("🔎 연도별 새롭게 진입한 전체 세부 주제 목록 보기"):
            st.dataframe(
                df_turnover[["연도", "전체_세부주제수", "신규진입비율(%)", "신규진입_주제목록"]],
                use_container_width=True,
                hide_index=True
            )

        st.markdown("---")

        # =====================================================
        # 섹션 2: 연구 질문 2 - 특정(선택) 주제 내 도서 최다 대출건수 및 순위 변화
        # =====================================================
        st.subheader("2️⃣ 선택 주제 내 베스트셀러 도서의 최다 대출건수 및 순위 변화")
        st.caption(
            f"선택하신 관심 주제(**{', '.join(selected_topic_labels)}**) 안에서 연도별로 가장 높은 인기를 얻은 도서의 "
            "**최다 대출건수 추이**와 **순위 변화**를 분석합니다."
        )

        if df_selected_raw.empty:
            st.warning(
                f"선택하신 기간({years_sorted[0]}~{years_sorted[-1]}년)의 전체 상위 {top_n}위 내에는 "
                f"선택하신 관심 주제 도서가 없습니다. 왼쪽 사이드바에서 **상위 순위 기준(예: Top 50, Top 100)**을 넓혀 보세요."
            )
        else:
            # 연도 x 선택 주제 전체 조합 격자 생성
            grid = pd.MultiIndex.from_product(
                [years_sorted, selected_topic_labels],
                names=["연도", "대주제"]
            ).to_frame(index=False)

            # 각 (연도, 대주제)별 최다 대출 도서 및 집계 산출
            agg_rows = []
            for (yr, topic_label), group in df_selected_raw.groupby(["연도", "대주제"]):
                top_book_row = group.sort_values(by=["대출건수", "순위"], ascending=[False, True]).iloc[0]
                agg_rows.append({
                    "연도": yr,
                    "대주제": topic_label,
                    "진입도서수": int(len(group)),
                    "최다대출건수": int(group["대출건수"].max()),
                    "평균대출건수": round(float(group["대출건수"].mean()), 1),
                    "최고순위": int(group["순위"].min()),
                    "평균순위": round(float(group["순위"].mean()), 1),
                    "대표도서명": top_book_row["도서명"],
                    "대표도서저자": top_book_row["저자"],
                })

            df_agg = pd.DataFrame(agg_rows)
            df_topic_trend = pd.merge(grid, df_agg, on=["연도", "대주제"], how="left")
            df_topic_trend["진입도서수"] = df_topic_trend["진입도서수"].fillna(0).astype(int)
            df_topic_trend["최다대출건수_표시"] = df_topic_trend["최다대출건수"].fillna(0).astype(int)
            df_topic_trend["대표도서명"] = df_topic_trend["대표도서명"].fillna("해당 연도 Top N 진입 도서 없음")
            df_topic_trend["연도_문자"] = df_topic_trend["연도"].astype(str)

            q2_col1, q2_col2 = st.columns(2)

            with q2_col1:
                loan_metric = st.radio(
                    "대출건수 기준 선택:",
                    options=["최다대출건수", "평균대출건수"],
                    horizontal=True,
                    key="loan_metric_radio"
                )
                y_col = "최다대출건수_표시" if loan_metric == "최다대출건수" else "평균대출건수"

                fig_loan = px.line(
                    df_topic_trend,
                    x="연도_문자",
                    y=y_col,
                    color="대주제",
                    markers=True,
                    hover_data={"대표도서명": True, "진입도서수": True, "연도_문자": False},
                    title=f"선택 주제 내 연도별 도서 {loan_metric} 변화",
                    labels={
                        "연도_문자": "조회 연도",
                        y_col: f"{loan_metric} (건)",
                        "대주제": "관심 주제",
                        "대표도서명": "주제 내 1위 도서",
                        "진입도서수": "Top N 진입 도서수"
                    },
                    height=370
                )
                fig_loan.update_traces(line=dict(width=3), marker=dict(size=9))
                fig_loan.update_yaxes(rangemode="tozero")
                st.plotly_chart(fig_loan, use_container_width=True)

            with q2_col2:
                rank_metric = st.radio(
                    "순위 기준 선택:",
                    options=["최고순위", "평균순위"],
                    horizontal=True,
                    key="rank_metric_radio"
                )
                fig_rank = px.line(
                    df_topic_trend.dropna(subset=[rank_metric]),
                    x="연도_문자",
                    y=rank_metric,
                    color="대주제",
                    markers=True,
                    hover_data={"대표도서명": True, "진입도서수": True, "연도_문자": False},
                    title=f"선택 주제 내 연도별 도서 {rank_metric} 변화 (1위가 상단)",
                    labels={
                        "연도_문자": "조회 연도",
                        rank_metric: f"{rank_metric} (위)",
                        "대주제": "관심 주제",
                        "대표도서명": "주제 내 1위 도서",
                        "진입도서수": "Top N 진입 도서수"
                    },
                    height=370
                )
                fig_rank.update_traces(line=dict(width=3), marker=dict(size=9))
                fig_rank.update_yaxes(autorange="reversed", dtick=max(1, top_n // 10))
                st.plotly_chart(fig_rank, use_container_width=True)

            # 연도별 선택 주제 내 최다 대출(1위) 도서 요약표
            st.markdown("#### 🏆 연도별 선택 주제 내 최다 대출(1위) 도서 및 순위 추이")
            df_top_books_table = df_topic_trend.dropna(subset=["최고순위"]).copy()
            df_top_books_table["최고순위"] = df_top_books_table["최고순위"].astype(int).astype(str) + "위"
            df_top_books_table["최다대출건수"] = df_top_books_table["최다대출건수"].astype(int).apply(lambda x: f"{x:,}건")
            df_top_books_table = df_top_books_table.sort_values(by=["대주제", "연도"], ascending=[True, True])

            st.dataframe(
                df_top_books_table[["대주제", "연도_문자", "대표도서명", "대표도서저자", "최고순위", "최다대출건수", "진입도서수"]].rename(
                    columns={
                        "연도_문자": "연도",
                        "대표도서명": "주제 내 최다 대출 도서",
                        "대표도서저자": "저자",
                        "최고순위": "전체 최고 순위",
                        "최다대출건수": "최다 대출건수",
                        "진입도서수": "주제 내 진입 권수"
                    }
                ),
                use_container_width=True,
                hide_index=True
            )

            st.markdown("---")

            # =====================================================
            # 섹션 3: 선택 주제 상세 도서 데이터 및 다운로드
            # =====================================================
            st.subheader("3️⃣ 선택 주제 베스트셀러 전체 상세 데이터")
            df_display = df_selected_raw.sort_values(by=["연도", "순위"], ascending=[False, True])
            st.dataframe(
                df_display[["연도", "순위", "대주제", "세부주제", "도서명", "저자", "출판사", "대출건수"]],
                use_container_width=True,
                hide_index=True
            )

            csv_data = df_display.to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 선택 주제 분석 결과 CSV 다운로드",
                data=csv_data,
                file_name=f"selected_topic_trend_{years_sorted[0]}_{years_sorted[-1]}_top{top_n}.csv",
                mime="text/csv"
            )

    # =====================================================
    # 모드 2: 오른쪽 사이드바 - 단일 연도 베스트셀러 리스트 조회
    # =====================================================
    elif st.session_state.active_mode == "list":
        yr = st.session_state.list_year
        topic_code = st.session_state.list_topic
        top_n = st.session_state.list_top_n

        if yr is None or topic_code is None or top_n is None:
            st.info("👉 오른쪽 사이드바에서 **조회 연도**, **주제 분류**, **상위 순위 기준**을 모두 선택하면 베스트셀러 리스트가 나타납니다.")
            st.stop()

        topic_label = LIST_TOPIC_OPTIONS[topic_code]
        st.subheader(f"📋 {yr}년 [{topic_label}] 베스트셀러 Top {top_n} 리스트")

        try:
            with st.spinner(f"{yr}년 {topic_label} 베스트셀러 데이터를 불러오는 중입니다..."):
                df_list = fetch_bestsellers(api_key, yr, top_n, kdc_code=topic_code)
        except Exception as e:
            st.error(f"데이터 수집 중 오류가 발생했습니다: {e}")
            st.stop()

        if df_list.empty:
            st.warning("선택하신 조건에 해당하는 베스트셀러 데이터가 없습니다.")
            st.stop()

        m1, m2, m3 = st.columns(3)
        m1.metric("조회 도서 수", f"{len(df_list)}권", f"{yr}년 Top {top_n}")
        m2.metric("1위 도서", df_list.iloc[0]["도서명"][:16] + ("..." if len(df_list.iloc[0]["도서명"]) > 16 else ""), df_list.iloc[0]["저자"])
        m3.metric("최고 대출 건수", f"{df_list['대출건수'].max():,}건", "연간 누적 대출")

        st.dataframe(
            df_list[["순위", "대주제", "세부주제", "도서명", "저자", "출판사", "출판년도", "대출건수"]],
            use_container_width=True,
            hide_index=True,
            height=560
        )

        csv_list = df_list.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            label="📥 베스트셀러 리스트 CSV 다운로드",
            data=csv_list,
            file_name=f"bestseller_list_{yr}_{topic_code}_top{top_n}.csv",
            mime="text/csv"
        )