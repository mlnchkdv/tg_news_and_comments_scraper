import re
import asyncio
import time
import pandas as pd
import io
import telethon
from telethon.sync import TelegramClient
from telethon.tl.functions.messages import GetHistoryRequest
from datetime import datetime, timedelta
import streamlit as st
import plotly.express as px
from telethon.tl.types import InputPeerChannel
from telethon.tl.functions.channels import GetFullChannelRequest, GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch

# Configure page
st.set_page_config(
    page_title="Telegram Message Extractor",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Helper functions
def format_time(seconds):
    """Format time in seconds to a readable string."""
    if seconds < 60:
        return f"{seconds:.1f} сек"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f} мин"
    else:
        hours = seconds / 3600
        return f"{hours:.1f} ч"

def estimate_remaining_time(elapsed_time, progress):
    """Estimate remaining time based on elapsed time and progress."""
    if progress <= 0:
        return "неизвестно"
    
    estimated_total = elapsed_time / progress
    remaining = estimated_total - elapsed_time
    
    return format_time(remaining)

def get_dataframe_excel(df):
    """Convert dataframe to Excel bytes buffer."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Data')
    output.seek(0)
    return output.getvalue()

def get_dataframe_csv(df):
    """Convert dataframe to CSV bytes buffer."""
    return df.to_csv(index=False).encode('utf-8')

def parse_telegram_link(link):
    """Parse Telegram link and extract username or invite."""
    if not link:
        return None
    
    link = link.strip()
    
    # Handle t.me links
    if "t.me/" in link:
        # Handle t.me/joinchat or t.me/+
        if "/joinchat/" in link or "/+" in link:
            parts = link.split("/joinchat/") if "/joinchat/" in link else link.split("/+")
            if len(parts) > 1:
                return parts[1].strip()
        else:
            username = link.split("t.me/")[1].strip()
            return username
    
    # Handle direct usernames or invite links
    elif link.startswith("@"):
        return link[1:].strip()
    else:
        return link.strip()

# App title and sidebar
st.sidebar.title("🔎 Настройки Telegram API")

# API credentials section
with st.sidebar.expander("📱 Учетные данные API", expanded=True):
    accounts = []
    
    account1 = {
        "api_id": st.text_input("API ID", key="api_id_1", type="password"),
        "api_hash": st.text_input("API Hash", key="api_hash_1", type="password"),
        "phone": st.text_input("Номер телефона", key="phone_1", placeholder="+79123456789"),
    }
    accounts.append(account1)
    
    # Additional accounts
    show_more_accounts = st.checkbox("Добавить дополнительные аккаунты")
    
    if show_more_accounts:
        for i in range(2, 6):  # Support up to 5 accounts
            with st.expander(f"Аккаунт {i}"):
                account = {
                    "api_id": st.text_input(f"API ID", key=f"api_id_{i}", type="password"),
                    "api_hash": st.text_input(f"API Hash", key=f"api_hash_{i}", type="password"),
                    "phone": st.text_input(f"Номер телефона", key=f"phone_{i}", placeholder="+79123456789"),
                }
                
                if account["api_id"] and account["api_hash"] and account["phone"]:
                    accounts.append(account)

# Search parameters section
st.sidebar.markdown("---")
st.sidebar.subheader("🔍 Параметры поиска")

group_links = st.sidebar.text_area(
    "Группы Telegram (по одной на строку)",
    placeholder="@group_name\nt.me/group_name\nt.me/joinchat/invite_hash",
    help="Введите ссылки на группы Telegram по одной на строку"
)

keyword = st.sidebar.text_input(
    "Ключевое слово для поиска",
    placeholder="Введите слово или фразу для поиска",
)

message_limit = st.sidebar.number_input(
    "Лимит сообщений на группу",
    min_value=10,
    max_value=10000,
    value=500,
    step=100,
    help="Максимальное количество сообщений для извлечения из каждой группы"
)

# Main content
if st.sidebar.button("🚀 Извлечь посты", use_container_width=True, type="primary"):
    if not accounts[0]["api_id"] or not accounts[0]["api_hash"] or not accounts[0]["phone"]:
        st.error("❌ Пожалуйста, введите учетные данные API Telegram для первого аккаунта.")
    elif not group_links:
        st.error("❌ Пожалуйста, введите хотя бы одну группу Telegram для поиска.")
    elif not keyword:
        st.error("❌ Пожалуйста, введите ключевое слово для поиска.")
    else:
        try:
            # Parse Telegram group links
            groups = [link.strip() for link in group_links.split('\n') if link.strip()]
            groups = [parse_telegram_link(link) for link in groups]
            groups = [group for group in groups if group]  # Remove None values
            
            if not groups:
                st.error("❌ Не удалось найти действительные группы Telegram. Проверьте введенные ссылки.")
            else:
                # Initialize progress bar and status
                progress_bar = st.progress(0)
                status_container = st.empty()
                metrics_container = st.empty()
                time_container = st.empty()
                
                def update_progress(message, progress_value):
                    progress_bar.progress(progress_value)
                    status_container.markdown(f"**Статус:** {message}")
                
                # Show the number of groups and accounts
                active_accounts = [acc for acc in accounts if acc["api_id"] and acc["api_hash"] and acc["phone"]]
                st.info(f"🔍 Поиск по {len(groups)} группам с ключевым словом '{keyword}' через {len(active_accounts)} аккаунт(ов) Telegram.")
                
                # Preparation phase
                update_progress("🔄 Подготовка к поиску...", 0.05)
                
                # Start timing
                start_time = time.time()
                
                # Main async function for extraction
                async def run_extraction():
                    # Initialize tracking variables
                    posts_found = 0
                    processed_groups = 0
                    total_messages_processed = 0
                    start_time_inner = time.time()
                    
                    # Create a metrics display function
                    def update_metrics():
                        elapsed = time.time() - start_time_inner
                        remaining = estimate_remaining_time(elapsed, (processed_groups / max(1, len(groups))))
                        
                        col1, col2, col3 = metrics_container.columns(3)
                        col1.metric("📊 Найдено постов", f"{posts_found}")
                        col2.metric("🔄 Обработано групп", f"{processed_groups}/{len(groups)}")
                        col3.metric("📝 Проверено сообщений", f"{total_messages_processed}")
                        
                        time_container.markdown(f"⏱️ Прошло: {format_time(elapsed)} | Осталось примерно: {remaining}")
                    
                    try:
                        # Create and authenticate clients
                        active_clients = []
                        
                        update_progress("🔌 Подключение к Telegram API...", 0.1)
                        for i, account in enumerate(active_accounts):
                            try:
                                # Create client session directory
                                session_name = f"session_{i}"
                                
                                # Create and connect client
                                client = TelegramClient(session_name, int(account["api_id"]), account["api_hash"])
                                await client.connect()
                                
                                # Check authorization
                                if not await client.is_user_authorized():
                                    update_progress(f"🔑 Авторизация аккаунта {account['phone']}...", 0.1)
                                    await client.send_code_request(account["phone"])
                                    
                                    # Create an input field for verification code
                                    code_input = status_container.text_input(
                                        f"Введите код подтверждения для {account['phone']}:",
                                        key=f"code_{i}"
                                    )
                                    
                                    if code_input:
                                        try:
                                            await client.sign_in(account["phone"], code_input)
                                            status_container.success(f"✅ Аккаунт {account['phone']} успешно авторизован!")
                                        except Exception as e:
                                            status_container.error(f"❌ Ошибка авторизации: {str(e)}")
                                            continue
                                
                                # If authorized, add to active clients
                                if await client.is_user_authorized():
                                    active_clients.append(client)
                                    status_container.success(f"✅ Аккаунт {account['phone']} подключен и готов к работе")
                            except Exception as e:
                                status_container.error(f"❌ Ошибка подключения аккаунта {account['phone']}: {str(e)}")
                        
                        # Check if we have any active clients
                        if not active_clients:
                            return None, "❌ Не удалось подключить ни один аккаунт Telegram. Проверьте учетные данные."
                        
                        # Process each group
                        update_progress("🔍 Начинаем поиск сообщений в группах...", 0.15)
                        
                        results = []
                        
                        # Function to process a group
                        async def process_group(group_link, client_index):
                            nonlocal posts_found, processed_groups, total_messages_processed
                            
                            client = active_clients[client_index % len(active_clients)]
                            
                            group_messages = []
                            
                            try:
                                # Get entity info
                                entity = await client.get_entity(group_link)
                                
                                # Get group title
                                try:
                                    group_info = await client(GetFullChannelRequest(channel=entity))
                                    group_title = group_info.chats[0].title
                                except:
                                    group_title = group_link
                                
                                # Update status with current group info
                                current_progress = 0.15 + (0.8 * processed_groups / len(groups))
                                update_progress(f"🔍 Поиск в группе '{group_title}' ({processed_groups+1}/{len(groups)})...", current_progress)
                                
                                # Get message history
                                messages_processed = 0
                                offset_id = 0
                                
                                while messages_processed < message_limit:
                                    batch_size = min(100, message_limit - messages_processed)
                                    history = await client(GetHistoryRequest(
                                        peer=entity,
                                        offset_id=offset_id,
                                        offset_date=None,
                                        add_offset=0,
                                        limit=batch_size,
                                        max_id=0,
                                        min_id=0,
                                        hash=0
                                    ))
                                    
                                    # Break if no more messages
                                    if not history.messages:
                                        break
                                    
                                    for message in history.messages:
                                        messages_processed += 1
                                        total_messages_processed += 1
                                        
                                        # Update metrics regularly
                                        if total_messages_processed % 100 == 0:
                                            update_metrics()
                                        
                                        if message.message:
                                            # Check for keyword
                                            if keyword.lower() in message.message.lower():
                                                sender_id = message.from_id.user_id if hasattr(message.from_id, 'user_id') else None
                                                
                                                # Get sender info
                                                sender_username = None
                                                sender_name = None
                                                
                                                if sender_id:
                                                    try:
                                                        sender = await client.get_entity(sender_id)
                                                        sender_username = sender.username if hasattr(sender, 'username') else None
                                                        sender_name = f"{sender.first_name or ''} {sender.last_name or ''}".strip()
                                                    except:
                                                        pass
                                                
                                                # Extract message data
                                                message_data = {
                                                    "message_id": message.id,
                                                    "date": message.date,
                                                    "group": group_title,
                                                    "group_link": f"https://t.me/{group_link}" if not group_link.startswith('+') else f"https://t.me/joinchat/{group_link}",
                                                    "message_link": f"https://t.me/{group_link}/{message.id}" if not group_link.startswith('+') else None,
                                                    "text": message.message,
                                                    "sender_id": sender_id,
                                                    "sender_username": sender_username,
                                                    "sender_name": sender_name,
                                                    "views": message.views if hasattr(message, 'views') else None,
                                                    "forwards": message.forwards if hasattr(message, 'forwards') else None,
                                                }
                                                
                                                group_messages.append(message_data)
                                                posts_found += 1
                                        
                                        # Update status with progress
                                        if messages_processed % 50 == 0:
                                            sub_progress = 0.15 + ((processed_groups + (messages_processed / message_limit)) / len(groups)) * 0.8
                                            update_progress(f"🔍 Поиск в группе '{group_title}' ({processed_groups+1}/{len(groups)}) - {messages_processed}/{message_limit} сообщений...", sub_progress)
                                    
                                    # Update offset for next batch
                                    offset_id = history.messages[-1].id
                                
                                # Update processed groups counter
                                processed_groups += 1
                                
                                # Return the messages found in this group
                                return group_messages
                            
                            except Exception as e:
                                processed_groups += 1
                                return []
                        
                        # Process groups in parallel with load balancing
                        tasks = []
                        for i, group in enumerate(groups):
                            tasks.append(process_group(group, i))
                        
                        group_results = await asyncio.gather(*tasks)
                        
                        # Combine all results
                        for group_messages in group_results:
                            if group_messages:
                                results.extend(group_messages)
                        
                        # Close all clients
                        for client in active_clients:
                            await client.disconnect()
                        
                        # Convert results to DataFrame
                        if results:
                            df = pd.DataFrame(results)
                            
                            # Format date
                            df['date'] = df['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # Sort by date (newest first)
                            df = df.sort_values('date', ascending=False)
                            
                            return df, "✅ Поиск успешно завершен!"
                        else:
                            return None, "⚠️ Сообщения с указанным ключевым словом не найдены."
                        
                    except Exception as e:
                        for client in active_clients:
                            try:
                                await client.disconnect()
                            except:
                                pass
                        return None, f"❌ Ошибка при выполнении поиска: {str(e)}"
                
                # Helper functions for time estimation
                def format_time(seconds):
                    if seconds < 60:
                        return f"{int(seconds)} сек"
                    elif seconds < 3600:
                        minutes = int(seconds // 60)
                        seconds = int(seconds % 60)
                        return f"{minutes} мин {seconds} сек"
                    else:
                        hours = int(seconds // 3600)
                        minutes = int((seconds % 3600) // 60)
                        return f"{hours} ч {minutes} мин"
                
                def estimate_remaining_time(elapsed, progress):
                    if progress <= 0:
                        return "расчет..."
                    
                    total_estimated = elapsed / progress
                    remaining = total_estimated - elapsed
                    
                    return format_time(remaining)
                
                # Run the extraction
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                
                try:
                    result_df, message = loop.run_until_complete(run_extraction())
                    
                    # Complete the progress
                    progress_bar.progress(1.0)
                    status_container.markdown(f"**Статус:** {message}")
                    
                    if result_df is not None:
                        elapsed_time = time.time() - start_time
                        st.success(f"✅ Поиск завершен за {format_time(elapsed_time)}. Найдено {len(result_df)} сообщений с ключевым словом '{keyword}'.")
                        
                        # Display results
                        st.dataframe(result_df)
                        
                        # Download buttons
                        col1, col2 = st.columns(2)
                        
                        with col1:
                            st.download_button(
                                label="📥 Скачать как Excel",
                                data=get_dataframe_excel(result_df),
                                file_name=f"telegram_search_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                mime="application/vnd.ms-excel"
                            )
                        
                        with col2:
                            st.download_button(
                                label="📥 Скачать как CSV",
                                data=get_dataframe_csv(result_df),
                                file_name=f"telegram_search_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                mime="text/csv"
                            )
                    else:
                        st.warning(message)
                
                except Exception as e:
                    st.error(f"❌ Произошла ошибка: {str(e)}")
                
                finally:
                    loop.close()
        
        except Exception as e:
            st.error(f"❌ Неожиданная ошибка: {str(e)}")

else:
    # Show welcome screen when not running
    st.title("🔍 Telegram Group Message Search")
    st.markdown("""
    ### 👋 Добро пожаловать в инструмент поиска сообщений в группах Telegram!
    
    #### 📋 Инструкции:
    1. Введите учетные данные API Telegram в боковой панели
    2. Добавьте ссылки на группы Telegram для поиска
    3. Укажите ключевое слово для поиска
    4. Настройте лимит сообщений (если необходимо)
    5. Нажмите кнопку "Извлечь посты", чтобы начать
    
    #### 🔑 Где получить данные API:
    1. Перейдите на [my.telegram.org](https://my.telegram.org/)
    2. Войдите в свой аккаунт Telegram
    3. Перейдите в "API development tools"
    4. Создайте новое приложение и получите API ID и Hash
    
    #### 📱 Поддерживаемые форматы ссылок на группы:
    - `@username`
    - `t.me/username`
    - `t.me/joinchat/invite_hash`
    - `t.me/+invite_hash`
    
    #### ⚙️ Конфиденциальность:
    - Все данные учетных записей остаются на вашем устройстве
    - Приложение не сохраняет и не передает ваши данные API
    """)
    
    # Show feature summary
    with st.expander("🌟 Возможности приложения"):
        st.markdown("""
        - 🔍 Поиск сообщений по ключевым словам в нескольких группах
        - 👥 Поддержка нескольких аккаунтов Telegram для обхода ограничений API
        - 📊 Экспорт результатов в Excel и CSV
        - ⏱️ Оценка оставшегося времени и прогресса
        - 🔄 Параллельная обработка групп для ускорения поиска
        """)