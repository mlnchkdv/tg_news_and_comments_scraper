import streamlit as st
import asyncio
import pandas as pd
import os
import re
import time
import json
from telethon import TelegramClient, sync
from telethon.tl.functions.messages import GetHistoryRequest
from io import BytesIO

# Page config
st.set_page_config(
    page_title="Экстрактор постов из групп Telegram",
    page_icon="📱",
    layout="wide"
)

# Title and description
st.title("📱 Экстрактор постов из групп Telegram")
st.markdown("""
Это приложение позволяет извлекать посты из указанных групп Telegram на основе ключевых слов или выражений.
Введите учетные данные API, укажите группы и ключевое слово для поиска, и загрузите результаты.
""")

# Telegram Extractor functions
async def extract_messages(client, group_links, keyword, limit=1000):
    """
    Извлечение сообщений из указанных групп Telegram, содержащих ключевое слово
    """
    results = []
    
    for group_link in group_links:
        try:
            # Handle group link format (remove https://t.me/ if present)
            if 'https://t.me/' in group_link:
                group_name = group_link.split('https://t.me/')[1]
            else:
                group_name = group_link
            
            # Get the entity (channel/group)
            entity = await client.get_entity(group_name)
            
            # Get messages
            messages = await client(GetHistoryRequest(
                peer=entity,
                limit=limit,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0
            ))
            
            # Filter messages containing the keyword (case insensitive)
            pattern = re.compile(keyword, re.IGNORECASE)
            
            for message in messages.messages:
                if message.message and pattern.search(message.message):
                    # Get message sender
                    try:
                        if message.from_id:
                            sender = await client.get_entity(message.from_id)
                            sender_name = f"{sender.first_name} {sender.last_name if sender.last_name else ''}"
                            sender_username = sender.username if hasattr(sender, 'username') else None
                        else:
                            sender_name = "Неизвестно"
                            sender_username = None
                    except:
                        sender_name = "Неизвестно"
                        sender_username = None
                        
                    results.append({
                        'группа': group_name,
                        'дата': message.date,
                        'отправитель': sender_name,
                        'имя_пользователя': sender_username,
                        'сообщение': message.message,
                        'id_сообщения': message.id,
                        'ссылка': f"https://t.me/{group_name}/{message.id}"
                    })
            
        except Exception as e:
            st.error(f"❌ Ошибка при извлечении сообщений из {group_link}: {str(e)}")
            
    # Create DataFrame
    df = pd.DataFrame(results)
    
    # Sort by date (newest first)
    if not df.empty:
        df = df.sort_values(by='дата', ascending=False)
        
    return df

def get_dataframe_excel(df):
    """Convert DataFrame to Excel file bytes for download"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Посты Telegram', index=False)
    output.seek(0)
    return output.getvalue()

def get_dataframe_csv(df):
    """Convert DataFrame to CSV file bytes for download"""
    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return output.getvalue()

def save_account(name, api_id, api_hash):
    """Сохранить аккаунт в список сохраненных аккаунтов"""
    accounts = load_accounts()
    accounts[name] = {"api_id": api_id, "api_hash": api_hash}
    
    with open("telegram_accounts.json", "w", encoding="utf-8") as f:
        json.dump(accounts, f, ensure_ascii=False, indent=4)

def load_accounts():
    """Загрузить сохраненные аккаунты"""
    try:
        with open("telegram_accounts.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    
def delete_account(name):
    """Удалить аккаунт из списка сохраненных"""
    accounts = load_accounts()
    if name in accounts:
        del accounts[name]
        with open("telegram_accounts.json", "w", encoding="utf-8") as f:
            json.dump(accounts, f, ensure_ascii=False, indent=4)
        return True
    return False

# Sidebar for inputs
with st.sidebar:
    st.header("🔑 Учетные данные Telegram API")
    
    # Account selection section
    accounts = load_accounts()
    account_options = ["Создать новый аккаунт"] + list(accounts.keys())
    selected_account = st.selectbox(
        "👤 Выберите аккаунт или создайте новый",
        account_options
    )
    
    if selected_account == "Создать новый аккаунт":
        st.markdown("""
        Чтобы использовать это приложение, вам нужны учетные данные API Telegram.
        Получите их на [my.telegram.org](https://my.telegram.org/auth?to=apps).
        """)
        
        account_name = st.text_input("🏷️ Название аккаунта", placeholder="Мой аккаунт")
        api_id = st.text_input("🆔 API ID", type="password")
        api_hash = st.text_input("🔐 API Hash", type="password")
        
        if st.button("💾 Сохранить аккаунт"):
            if account_name and api_id and api_hash:
                save_account(account_name, api_id, api_hash)
                st.success(f"✅ Аккаунт '{account_name}' успешно сохранен!")
                st.rerun()
            else:
                st.error("❌ Заполните все поля для сохранения аккаунта")
    else:
        # Display selected account info
        api_id = accounts[selected_account]["api_id"]
        api_hash = accounts[selected_account]["api_hash"]
        st.success(f"✅ Выбран аккаунт: {selected_account}")
        
        # Option to delete the account
        if st.button("🗑️ Удалить этот аккаунт"):
            if delete_account(selected_account):
                st.success(f"✅ Аккаунт '{selected_account}' успешно удален!")
                st.rerun()
            else:
                st.error("❌ Ошибка при удалении аккаунта")
    
    st.header("🔍 Параметры поиска")
    
    # Group links - one per line
    group_links = st.text_area(
        "📋 Ссылки на группы Telegram (по одной на строку)",
        placeholder="groupname1\ngroupname2\nhttps://t.me/groupname3",
        help="Введите ссылки на группы Telegram или имена пользователей групп, по одной на строку"
    )
    
    # Keyword or expression
    keyword = st.text_input(
        "🔤 Ключевое слово или выражение",
        placeholder="Введите поисковый запрос",
        help="Будут извлечены сообщения, содержащие это ключевое слово или выражение"
    )
    
    # Message limit
    message_limit = st.number_input(
        "📊 Максимальное количество сообщений для извлечения из каждой группы",
        min_value=100,
        max_value=5000,
        value=1000,
        step=100,
        help="Большие значения могут занять больше времени для обработки"
    )
    
    # Extract button
    extract_button = st.button("🚀 Извлечь сообщения", type="primary")

# Main content area
if extract_button:
    if not api_id or not api_hash:
        st.error("❌ Пожалуйста, введите учетные данные API Telegram")
    elif not group_links:
        st.error("❌ Пожалуйста, введите хотя бы одну группу Telegram")
    elif not keyword:
        st.error("❌ Пожалуйста, введите ключевое слово или выражение для поиска")
    else:
        # Process the group links (split by newline and remove empty lines)
        group_list = [line.strip() for line in group_links.split('\n') if line.strip()]
        
        with st.spinner(f"⏳ Извлечение сообщений, содержащих '{keyword}' из {len(group_list)} групп..."):
            try:
                # Run the extraction asynchronously
                async def run_extraction():
                    client = TelegramClient('anon', api_id, api_hash)
                    await client.start()
                    df = await extract_messages(client, group_list, keyword, limit=message_limit)
                    await client.disconnect()
                    return df
                
                # Run the async function
                df = asyncio.run(run_extraction())
                
                # Display results
                if df.empty:
                    st.warning(f"⚠️ Не найдено сообщений, содержащих '{keyword}' в указанных группах.")
                else:
                    st.success(f"✅ Найдено {len(df)} сообщений, содержащих '{keyword}'!")
                    
                    # Show dataframe
                    st.dataframe(
                        df[['группа', 'дата', 'отправитель', 'сообщение', 'ссылка']],
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    # Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        excel_data = get_dataframe_excel(df)
                        st.download_button(
                            label="📥 Скачать как Excel",
                            data=excel_data,
                            file_name=f"telegram_posts_{keyword}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    
                    with col2:
                        csv_data = get_dataframe_csv(df)
                        st.download_button(
                            label="📥 Скачать как CSV",
                            data=csv_data,
                            file_name=f"telegram_posts_{keyword}_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                    
            except Exception as e:
                st.error(f"❌ Произошла ошибка: {str(e)}")

# Add footer
st.markdown("---")
st.markdown("📱 Экстрактор постов из групп Telegram | Создано с помощью Streamlit и Telethon")