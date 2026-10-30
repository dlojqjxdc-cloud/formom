import os
import re
import uuid
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit, parse_qs, urlencode

import streamlit as st
import qrcode

st.set_page_config(page_title="장보기 알림메모", page_icon="🛒", layout="centered", initial_sidebar_state="collapsed")
DB_PATH = os.environ.get("SHOPPING_DB_PATH", "shopping_memo.sqlite3")
CATEGORIES = ["🥬 야채", "🍎 과일", "🥩 정육·달걀", "🐟 수산", "🥛 유제품", "🍚 쌀·곡물", "🥫 가공식품", "🧴 생활용품", "📦 기타"]
PRIORITIES = {1: "1 · 꼭 구매", 2: "2 · 적정가면 구매", 3: "3 · 비싸면 패스"}


def connect():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    return con


@st.cache_resource
def initialize_database():
    with connect() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY, memo TEXT NOT NULL, category TEXT NOT NULL,
            name TEXT NOT NULL, priority INTEGER NOT NULL CHECK(priority BETWEEN 1 AND 3),
            status TEXT NOT NULL DEFAULT 'pending', unit_price INTEGER, quantity TEXT,
            subtotal INTEGER, created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
    return True


initialize_database()
raw_token = st.query_params.get("memo", "")
if not re.fullmatch(r"[a-f0-9]{32}", raw_token):
    raw_token = uuid.uuid4().hex
    st.query_params["memo"] = raw_token
MEMO = raw_token


def rows():
    with connect() as con:
        return [dict(r) for r in con.execute(
            "SELECT * FROM items WHERE memo=? ORDER BY priority, created, id", (MEMO,)
        ).fetchall()]


def flash(message):
    st.session_state["notice"] = message


def update_status(item_id, status):
    with connect() as con:
        con.execute("UPDATE items SET status=?,unit_price=NULL,quantity=NULL,subtotal=NULL WHERE id=? AND memo=?", (status, item_id, MEMO))


@st.dialog("🛒 카트에 담기")
def purchase(item):
    st.write(f"**{item['name']}** · {PRIORITIES[item['priority']]}")
    if item["priority"] > 1:
        st.info("비싸면 지금 구매하지 않고 ‘이번엔 패스’를 눌러도 괜찮아요.")
    with st.form("purchase_form"):
        a, b = st.columns(2)
        price = a.number_input("단가(원)", min_value=0, max_value=100_000_000, step=100, value=1000)
        quantity = b.number_input("수량", min_value=0.01, max_value=10000.0, value=1.0, step=1.0, format="%.2f")
        st.caption("묶음 상품은 단가에 묶음 가격, 수량에 묶음 수를 입력하세요. 무게 구매도 소수 수량으로 입력할 수 있어요. 합계는 원 단위 반올림합니다.")
        submitted = st.form_submit_button("가격·수량 저장하고 담기", type="primary", use_container_width=True)
        if submitted:
            qty = Decimal(str(quantity))
            subtotal = int((Decimal(int(price)) * qty).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            with connect() as con:
                con.execute("UPDATE items SET status='cart',unit_price=?,quantity=?,subtotal=? WHERE id=? AND memo=? AND status='pending'", (int(price), str(qty), subtotal, item["id"], MEMO))
            flash(f"{item['name']} · {subtotal:,}원 담았어요")
            st.rerun()
    if st.button("이번엔 패스", use_container_width=True):
        update_status(item["id"], "deferred")
        flash("목록에서 보류했어요. ‘보류’에서 다시 복원할 수 있어요.")
        st.rerun()


@st.dialog("✏️ 품목 수정")
def edit_item(item):
    with st.form("edit_form"):
        name = st.text_input("상품명", value=item["name"], max_chars=60)
        category = st.selectbox("카테고리", CATEGORIES, index=CATEGORIES.index(item["category"]))
        priority = st.selectbox("중요도", [1, 2, 3], index=item["priority"] - 1, format_func=lambda p: PRIORITIES[p])
        if st.form_submit_button("저장", type="primary", use_container_width=True):
            if not name.strip():
                st.error("상품명을 입력해 주세요.")
            else:
                with connect() as con:
                    con.execute("UPDATE items SET name=?,category=?,priority=? WHERE id=? AND memo=?", (name.strip(), category, priority, item["id"], MEMO))
                st.rerun()


@st.dialog("🔗 QR로 같은 메모 열기")
def share():
    st.caption("배포된 앱 주소를 입력하세요. localhost 주소는 다른 휴대폰에서 열리지 않습니다.")
    default = getattr(st.context, "url", "") or ""
    base = st.text_input("앱의 공개 주소", value=default, placeholder="https://my-shopping.streamlit.app")
    if base:
        parts = urlsplit(base.strip())
        if parts.scheme not in ("http", "https") or not parts.netloc:
            st.warning("https:// 로 시작하는 올바른 앱 주소를 입력하세요.")
        else:
            query = parse_qs(parts.query)
            query["memo"] = [MEMO]
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), ""))
            image = qrcode.make(url)
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            st.image(buffer.getvalue(), width=210)
            st.link_button("이 메모 열기", url, use_container_width=True)
            st.download_button("QR 이미지 다운로드", buffer.getvalue(), "shopping-qr.png", "image/png", use_container_width=True)
            st.caption("주소를 북마크하세요. 이 주소/QR을 가진 사람은 같은 메모를 보고 수정할 수 있습니다. 공개 게시하지 마세요.")
    st.warning("저장 안내: 데이터는 앱 서버의 SQLite 파일에 저장됩니다. Streamlit Community Cloud의 재배포·서버 교체 시 사라질 수 있습니다. 영구 보관은 외부 DB 연결이 필요합니다.")
    if st.button("빈 새 메모 만들기", use_container_width=True):
        st.query_params["memo"] = uuid.uuid4().hex
        st.rerun()


@st.dialog("🧾 장보기 마무리")
def finish():
    cart = [i for i in rows() if i["status"] == "cart"]
    st.write(f"카트 **{len(cart)}종 · {sum(i['subtotal'] or 0 for i in cart):,}원**")
    st.caption("마무리하면 현재 카트는 비워지고 영수증 기록으로 남습니다. 미구매·보류 메모는 유지됩니다.")
    if st.button("확인하고 카트 비우기", type="primary", use_container_width=True, disabled=not cart):
        with connect() as con:
            con.execute("UPDATE items SET status='purchased' WHERE memo=? AND status='cart'", (MEMO,))
        flash("장보기를 마쳤어요. ‘기록’에서 구매 내역을 확인하세요.")
        st.rerun()


st.markdown("""<style>
.block-container{max-width:660px;padding:0.7rem 0.7rem 0.5rem!important}
header[data-testid="stHeader"]{display:none}
[data-testid="stMainBlockContainer"]{padding-top:0.7rem!important}
[data-testid="stVerticalBlock"]{gap:0.35rem}
h3{padding:0!important;margin:0!important;font-size:1.3rem!important}
[data-testid="stMetricValue"]{font-size:1.5rem}
[data-testid="stMetricLabel"]{font-size:0.8rem}
[data-testid="stHorizontalBlock"]{gap:0.4rem;flex-wrap:nowrap!important}
[data-testid="stHorizontalBlock"]>[data-testid="stColumn"]{min-width:0!important}
[data-testid="stForm"]{padding:0.45rem;border-radius:14px}
.stButton button,.stFormSubmitButton button{min-height:2.15rem;padding:0.2rem 0.4rem;font-size:0.85rem}
[data-testid="stCaptionContainer"] p{font-size:0.73rem;margin-bottom:0}
[data-testid="stBottom"]{display:none}
</style>""", unsafe_allow_html=True)

heading, qr = st.columns([4, 1])
heading.markdown("### 🛒 장보기 알림메모")
if qr.button("QR", use_container_width=True):
    share()

items = rows()
cart = [i for i in items if i["status"] == "cart"]
pending = [i for i in items if i["status"] == "pending"]
a, b, c = st.columns(3)
a.metric("카트 총액", f"{sum(i['subtotal'] or 0 for i in cart):,}원")
b.metric("담은 품목", f"{len(cart)}종")
c.metric("남은 메모", f"{len(pending)}종")

with st.form("add_form", clear_on_submit=True):
    a, b = st.columns([1.05, 1.95])
    category = a.selectbox("분류", CATEGORIES, label_visibility="collapsed")
    name = b.text_input("상품명", max_chars=60, placeholder="상품명 · 예: 방울토마토", label_visibility="collapsed")
    a, b = st.columns([2.2, 1])
    priority = a.selectbox("중요도", [1, 2, 3], index=1, format_func=lambda p: PRIORITIES[p], label_visibility="collapsed")
    add = b.form_submit_button("＋ 추가", type="primary", use_container_width=True)
    if add:
        if name.strip():
            with connect() as con:
                con.execute("INSERT INTO items(id,memo,category,name,priority) VALUES(?,?,?,?,?)", (uuid.uuid4().hex, MEMO, category, name.strip(), priority))
            flash("메모를 추가했어요")
            st.rerun()
        else:
            st.toast("상품명을 입력해 주세요.")

view = st.radio("목록", ["살 것", "카트", "보류", "기록"], horizontal=True, label_visibility="collapsed")
status = {"살 것": "pending", "카트": "cart", "보류": "deferred", "기록": "purchased"}[view]
visible = [i for i in items if i["status"] == status]
# Only the list scrolls when there are many items; the page stays compact on typical phones.
with st.container(height=155, border=True):
    if not visible:
        st.caption({"살 것": "살 물건을 위에서 추가하세요 📝", "카트": "물건을 담으면 금액이 표시돼요 🛒", "보류": "비싼 물건은 잠시 패스해도 괜찮아요 🌿", "기록": "장보기를 마무리하면 구매 기록이 남아요 🧾"}[view])
    for index, item in enumerate(visible, 1):
        if status in ("cart", "purchased"):
            st.caption(f"{index}. {item['name']} · {item['unit_price']:,}원 × {Decimal(item['quantity']):g} = {item['subtotal']:,}원")
        else:
            badge = {1: "🔴", 2: "🟡", 3: "🟢"}[item["priority"]]
            st.caption(f"{index}. {badge} {item['name']} · {item['category']} · 중요도 {item['priority']}")

if visible:
    selected = st.selectbox("작업할 품목", options=[i["id"] for i in visible], format_func=lambda iid: next(f"{n}. {i['name']}" for n, i in enumerate(visible, 1) if i["id"] == iid), label_visibility="collapsed", key=f"selected_{status}")
    item = next(i for i in visible if i["id"] == selected)
    if status == "pending":
        a, b, c = st.columns([1.5, 1, 1])
        if a.button("🛒 담기", type="primary", use_container_width=True):
            purchase(item)
        if b.button("보류", use_container_width=True):
            update_status(item["id"], "deferred")
            st.rerun()
        if c.button("수정", use_container_width=True):
            edit_item(item)
    elif status == "cart":
        a, b = st.columns(2)
        if a.button("↩ 담기 취소", use_container_width=True):
            update_status(item["id"], "pending")
            st.rerun()
        if b.button("장보기 마무리", type="primary", use_container_width=True):
            finish()
    elif status == "deferred":
        a, b = st.columns(2)
        if a.button("↩ 살 것에 복원", use_container_width=True):
            update_status(item["id"], "pending")
            st.rerun()
        if b.button("수정", use_container_width=True):
            edit_item(item)
    else:
        st.caption(f"누적 구매 기록 합계 {sum(i['subtotal'] or 0 for i in visible):,}원 · 현재 카트 총액에는 포함되지 않아요.")

notice = st.session_state.pop("notice", None)
if notice:
    st.toast(notice)
st.caption("🔴 꼭 구매 · 🟡 적정가면 구매 · 🟢 비싸면 패스")
