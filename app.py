import streamlit as st
import pandas as pd
import requests

# 페이지 기본 설정
st.set_page_config(page_title="도서 베스트셀러 트렌드 분석", layout="wide")

st.title("📚 도서 대출 베스트셀러 트렌드 분석 (team12)")

# 한국십진분류법(KDC) 대분류 목록 및 API 코드 매핑
KDC_TOPICS = {
    "총류": "0", "철학": "1", "종교": "2", "사회과학": "3",
    "자연과학": "4", "기술과학": "5", "예술": "6", "언어": "7",
    "문학": "8", "역사": "9"
}

# 2026년부터 2016년까지 역순으로 연도 목록 생성
YEARS = [str(year) for year in range(2026, 2015, -1)]

# 1. 왼쪽 사이드바 구성
with st.sidebar:
    st.header("조건 선택")
    selected_year = st.selectbox("조회 연도", YEARS)
    selected_topic_name = st.selectbox("관심 주제 (KDC 대분류)", list(KDC_TOPICS.keys()))
    # 기획서 핵심 질문 1번("상위 20위 내")을 반영하여 기본값을 20으로 설정
    selected_rank = st.slider("상위 순위", 1, 100, 20)
    search_button = st.button("데이터 조회")


# 2. 데이터 수집 함수
def get_bestseller_data(year, topic_code, rank):
    # API 키는 GitHub에 직접 노출되지 않도록 secrets에서 불러옴
    API_KEY = st.secrets["API_KEY"]

    # 정보나루 인기대출도서 조회 API 엔드포인트
    url = "http://data4library.kr/api/loanItemSrch"

    # 선택된 연도의 1월 1일부터 12월 31일까지를 조회 기준으로 설정
    params = {
        "authKey": API_KEY,
        "startDt": f"{year}-01-01",
        "endDt": f"{year}-12-31",
        "kdc": topic_code,
        "pageNo": 1,
        "pageSize": rank,
        "format": "json"
    }

    try:
        response = requests.get(url, params=params)
        data = response.json()

        # 정보나루 API의 응답 구조(response -> docs -> doc)에 맞게 파싱
        if 'response' in data and 'docs' in data['response']:
            items = [doc['doc'] for doc in data['response']['docs']]
            df = pd.DataFrame(items)

            if not df.empty:
                # 데이터 분석에 필요한 항목만 추출
                df = df[['ranking', 'bookname', 'authors', 'publisher', 'publication_year', 'loan_count']]
                df.columns = ['순위', '도서명', '저자명', '출판사', '출판연도', '대출건수']

                # 순위를 기준으로 오름차순 정렬
                df['순위'] = pd.to_numeric(df['순위'])
                df = df.sort_values('순위').reset_index(drop=True)
            return df
        else:
            return pd.DataFrame()

    except Exception as e:
        st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
        return pd.DataFrame()


# 3. 메인 화면 출력
st.write("사이드바에서 조건을 선택하고 [데이터 조회] 버튼을 누르세요.")

if search_button:
    st.subheader(f"{selected_year}년 {selected_topic_name} 분야 상위 {selected_rank}위 베스트셀러")

    with st.spinner("데이터를 불러오는 중입니다..."):
        topic_code = KDC_TOPICS[selected_topic_name]
        df = get_bestseller_data(selected_year, topic_code, selected_rank)

        if not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.warning("조건에 맞는 데이터가 없습니다.")