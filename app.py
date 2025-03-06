import streamlit as st
import asyncio
import pandas as pd
import os
import re
import time
import random
from telethon import TelegramClient, sync, errors
from telethon.tl.functions.messages import GetHistoryRequest
from io import BytesIO
from datetime import datetime, timedelta

# Page config
st.set_page_config(
    page_title="Экстрактор сообщений Telegram 📱",
    page_icon="📱",
    layout="wide"
)

# Title and description
st.title("📱 Экстрактор сообщений из групп Telegram")
st.markdown("""
Это приложение позволяет извлекать сообщения из указанных групп Telegram на основе ключевых слов или выражений.
Введите данные вашего API, укажите группы и ключевые слова для поиска, затем загрузите результаты.
Вы можете указать несколько API-ключей для балансировки нагрузки между аккаунтами. 🚀
""")

# Telegram Extractor functions
async def check_account_status(client):
    """Проверка статуса аккаунта (забанен или нет)"""
    try:
        # Try to get dialogs as a simple check
        await client.get_dialogs(limit=1)
        return True, "✅ Аккаунт активен"
    except errors.UserDeactivatedBanError:
        return False, "❌ Аккаунт забанен"
    except errors.AuthKeyUnregisteredError:
        return False, "⚠️ Сессия истекла"
    except Exception as e:
        return False, f"⚠️ Ошибка проверки аккаунта: {str(e)}"

async def extract_messages(client, group_links, keyword, limit=1000, progress_callback=None):
    """
    Извлечение сообщений из указанных групп Telegram, содержащих ключевое слово
    """
    results = []
    total_groups = len(group_links)
    
    for i, group_link in enumerate(group_links):
        try:
            # Update progress
            if progress_callback:
                progress_callback(f"⏳ Обработка группы {i+1}/{total_groups}: {group_link}", (i / total_groups) * 0.8)
            
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
            
            for msg_idx, message in enumerate(messages.messages):
                # Update progress more frequently
                if progress_callback and msg_idx % 100 == 0:
                    progress_value = (i / total_groups) * 0.8 + (msg_idx / len(messages.messages)) * 0.2 / total_groups
                    progress_callback(f"🔍 Анализ сообщений в группе {group_name}: {msg_idx}/{len(messages.messages)}", progress_value)
                
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
                        'group': group_name,
                        'date': message.date,
                        'sender_name': sender_name,
                        'sender_username': sender_username,
                        'message': message.message,
                        'message_id': message.id,
                        'message_link': f"https://t.me/{group_name}/{message.id}"
                    })
                    
                    # Update progress after finding a match
                    if progress_callback and len(results) % 10 == 0:
                        progress_callback(f"✅ Найдено сообщений: {len(results)}", None)
            
        except Exception as e:
            if progress_callback:
                progress_callback(f"❌ Ошибка при извлечении сообщений из {group_link}: {str(e)}", None)
            
    # Create DataFrame
    df = pd.DataFrame(results)
    
    # Sort by date (newest first)
    if not df.empty:
        df = df.sort_values(by='date', ascending=False)
        
    return df

def get_dataframe_excel(df):
    """Конвертация DataFrame в файл Excel для скачивания"""
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, sheet_name='Посты Telegram', index=False)
    output.seek(0)
    return output.getvalue()

def get_dataframe_csv(df):
    """Конвертация DataFrame в файл CSV для скачивания"""
    output = BytesIO()
    df.to_csv(output, index=False)
    output.seek(0)
    return output.getvalue()

def format_time(seconds):
    """Форматирование времени в читаемый формат"""
    if seconds < 60:
        return f"{seconds:.0f} сек"
    elif seconds < 3600:
        minutes = seconds // 60
        seconds %= 60
        return f"{minutes:.0f} мин {seconds:.0f} сек"
    else:
        hours = seconds // 3600
        seconds %= 3600
        minutes = seconds // 60
        seconds %= 60
        return f"{hours:.0f} ч {minutes:.0f} мин {seconds:.0f} сек"

# Sidebar for inputs
with st.sidebar:
    st.header("🔑 Учетные данные Telegram API")
    st.markdown("""
    Для использования этого приложения вам нужны API-ключи Telegram. 
    Получите их на [my.telegram.org](https://my.telegram.org/auth?to=apps).
    
    Вы можете добавить несколько аккаунтов для балансировки нагрузки, введя несколько наборов учетных данных API.
    """)
    
    # Multiple account support
    num_accounts = st.number_input("📊 Количество аккаунтов Telegram", min_value=1, max_value=10, value=1)
    
    # Create containers for each account
    account_containers = []
    api_credentials = []
    
    for i in range(num_accounts):
        account_container = st.container()
        with account_container:
            st.subheader(f"📱 Аккаунт {i+1}")
            api_id = st.text_input(f"API ID #{i+1}", type="password", key=f"api_id_{i}")
            api_hash = st.text_input(f"API Hash #{i+1}", type="password", key=f"api_hash_{i}")
            api_credentials.append((api_id, api_hash))
        account_containers.append(account_container)
    
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
        help="Будут извлечены посты, содержащие это ключевое слово или выражение"
    )
    
    # Message limit
    message_limit = st.number_input(
        "🔢 Максимальное количество сообщений для извлечения из каждой группы",
        min_value=100,
        max_value=5000,
        value=1000,
        step=100,
        help="Большие значения могут занять больше времени для обработки"
    )
    
    # Extract button
    extract_button = st.button("🚀 Извлечь посты", type="primary")

# Main content area
if extract_button:
    # Check if at least one set of valid API credentials was provided
    valid_credentials = [(i, api_id, api_hash) for i, (api_id, api_hash) in enumerate(api_credentials) if api_id and api_hash]
    
    if not valid_credentials:
        st.error("⚠️ Пожалуйста, введите как минимум один набор действительных учетных данных API Telegram")
    elif not group_links:
        st.error("⚠️ Пожалуйста, введите хотя бы одну группу Telegram")
    elif not keyword:
        st.error("⚠️ Пожалуйста, введите ключевое слово или выражение для поиска")
    else:
        # Process the group links (split by newline and remove empty lines)
        group_list = [line.strip() for line in group_links.split('\n') if line.strip()]
        
        # Create status containers
        status_container = st.container()
        with status_container:
            st.subheader("🔄 Статус аккаунтов")
            status_placeholder = st.empty()
        
        progress_container = st.container()
        with progress_container:
            progress_bar = st.progress(0)
            progress_text = st.empty()
            time_info = st.empty()
            results_info = st.empty()
        
        # Record start time
        start_time = time.time()
        posts_found = 0
        
        def update_progress(message, progress_value=None):
            nonlocal posts_found
            if "Найдено сообщений:" in message:
                # Extract number of posts found
                posts_found = int(message.split("Найдено сообщений:")[1].strip())
            
            elapsed_time = time.time() - start_time
            progress_text.text(message)
            
            if progress_value is not None:
                progress_bar.progress(progress_value)
                if progress_value > 0:
                    estimated_total_time = elapsed_time / progress_value
                    remaining_time = estimated_total_time - elapsed_time
                    time_info.text(f"⏱️ Прошло: {format_time(elapsed_time)} | Осталось: {format_time(remaining_time)}")
            
            results_info.text(f"📊 Найдено сообщений: {posts_found}")
        
        with st.spinner(f"⏳ Проверка статуса аккаунта и извлечение постов с '{keyword}' из {len(group_list)} групп..."):
            try:
                # Run the extraction asynchronously
                async def run_extraction():
                    # Dictionary to track client status
                    clients = {}
                    active_clients = []
                    status_messages = []
                    
                    # Initialize and check all clients
                    update_progress("🔄 Инициализация и проверка аккаунтов Telegram...", 0.05)
                    
                    for i, api_id, api_hash in valid_credentials:
                        try:
                            client = TelegramClient(f'session_{i}', api_id, api_hash)
                            await client.start()
                            
                            # Check if account is banned
                            is_active, status_msg = await check_account_status(client)
                            status_messages.append(f"Аккаунт {i+1}: {status_msg}")
                            
                            if is_active:
                                active_clients.append(client)
                                clients[i] = {'client': client, 'status': 'active'}
                            else:
                                await client.disconnect()
                                clients[i] = {'client': None, 'status': 'inactive', 'reason': status_msg}
                        except Exception as e:
                            status_messages.append(f"Аккаунт {i+1}: ❌ Не удалось инициализировать - {str(e)}")
                            clients[i] = {'client': None, 'status': 'error', 'reason': str(e)}
                    
                    # Update status display
                    status_placeholder.markdown("\n".join(status_messages))
                    
                    update_progress("✅ Проверка аккаунтов завершена", 0.1)
                    
                    if not active_clients:
                        return pd.DataFrame(), "❌ Нет активных аккаунтов. Пожалуйста, проверьте свои учетные данные API."
                    
                    # Distribute groups among active clients for load balancing
                    all_results = []
                    
                    # Distribute groups evenly among active clients
                    num_active_clients = len(active_clients)
                    groups_per_client = {}
                    
                    for i, group in enumerate(group_list):
                        client_idx = i % num_active_clients
                        if client_idx not in groups_per_client:
                            groups_per_client[client_idx] = []
                        groups_per_client[client_idx].append(group)
                    
                    update_progress(f"⚖️ Распределение групп между {num_active_clients} активными аккаунтами", 0.15)
                    
                    # Process each client's assigned groups
                    tasks = []
                    for idx, groups in groups_per_client.items():
                        client = active_clients[idx]
                        tasks.append(extract_messages(client, groups, keyword, limit=message_limit, progress_callback=update_progress))
                    
                    # Wait for all tasks to complete
                    update_progress("🔍 Извлечение сообщений из всех групп...", 0.2)
                    results = await asyncio.gather(*tasks)
                    
                    # Combine all dataframes
                    update_progress("📊 Объединение результатов...", 0.9)
                    combined_df = pd.concat(results) if results else pd.DataFrame()
                    
                    # Sort by date
                    if not combined_df.empty:
                        combined_df = combined_df.sort_values(by='date', ascending=False)
                    
                    # Disconnect all clients
                    update_progress("🔌 Отключение клиентов Telegram...", 0.95)
                    for client in active_clients:
                        await client.disconnect()
                    
                    update_progress("✅ Обработка завершена!", 1.0)
                    return combined_df, None
                
                # Run the extraction asynchronously
                df, error = asyncio.run(run_extraction())
                
                # Handle results
                if error:
                    st.error(error)
                else:
                    total_time = time.time() - start_time
                    
                    # Display results
                    if not df.empty:
                        st.success(f"✅ Успешно извлечено {len(df)} сообщений за {format_time(total_time)}!")
                        
                        # Format the date column for display
                        display_df = df.copy()
                        display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
                        
                        # Create tabs for different views
                        tab1, tab2, tab3 = st.tabs(["📊 Таблица данных", "📈 Аналитика", "📥 Скачать"])
                        
                        with tab1:
                            st.dataframe(display_df, use_container_width=True)
                        
                        with tab2:
                            st.subheader("📊 Аналитика по найденным сообщениям")
                            
                            # Posts per group
                            st.subheader("📱 Сообщения по группам")
                            group_counts = df['group'].value_counts().reset_index()
                            group_counts.columns = ['Группа', 'Количество сообщений']
                            
                            fig1 = px.bar(group_counts, 
                                         x='Группа', 
                                         y='Количество сообщений',
                                         title="Распределение сообщений по группам",
                                         color='Количество сообщений')
                            st.plotly_chart(fig1, use_container_width=True)
                            
                            # Posts over time
                            st.subheader("📅 Временная динамика сообщений")
                            df['date_only'] = df['date'].dt.date
                            time_series = df.groupby('date_only').size().reset_index()
                            time_series.columns = ['Дата', 'Количество сообщений']
                            
                            fig2 = px.line(time_series, 
                                          x='Дата', 
                                          y='Количество сообщений',
                                          title="Динамика сообщений по датам",
                                          markers=True)
                            st.plotly_chart(fig2, use_container_width=True)
                            
                            # Top senders
                            if 'sender_username' in df.columns and not df['sender_username'].isna().all():
                                st.subheader("👤 Топ авторов сообщений")
                                sender_counts = df['sender_username'].value_counts().head(10).reset_index()
                                sender_counts.columns = ['Пользователь', 'Количество сообщений']
                                
                                fig3 = px.bar(sender_counts, 
                                             x='Пользователь', 
                                             y='Количество сообщений',
                                             title="Топ-10 авторов сообщений",
                                             color='Количество сообщений')
                                st.plotly_chart(fig3, use_container_width=True)
                        
                        with tab3:
                            st.subheader("📥 Скачать результаты")
                            
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                excel_data = get_dataframe_excel(df)
                                st.download_button(
                                    label="📊 Скачать Excel",
                                    data=excel_data,
                                    file_name=f"telegram_posts_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                                    mime="application/vnd.ms-excel"
                                )
                            
                            with col2:
                                csv_data = get_dataframe_csv(df)
                                st.download_button(
                                    label="📋 Скачать CSV",
                                    data=csv_data,
                                    file_name=f"telegram_posts_{keyword}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                                    mime="text/csv"
                                )
                    else:
                        st.warning(f"⚠️ Не найдено сообщений с ключевым словом '{keyword}' в указанных группах.")
                
            except Exception as e:
                st.error(f"❌ Произошла ошибка: {str(e)}")
                import traceback
                st.error(traceback.format_exc())
else:
    # App description and instructions when first loaded
    st.title("🔎 Поиск сообщений в Telegram")
    
    st.markdown("""
    ## 📱 Добро пожаловать в приложение для поиска сообщений в Telegram!
    
    Это приложение позволяет извлекать сообщения из групп Telegram, содержащие указанные ключевые слова.
    
    ### 🚀 Как использовать:
    
    1. **Введите учетные данные API Telegram** в боковой панели (получите их на [my.telegram.org](https://my.telegram.org))
    2. **Добавьте несколько аккаунтов** для распределения нагрузки (необязательно)
    3. **Укажите группы Telegram** для поиска (по одной на строку)
    4. **Введите ключевое слово** или фразу для поиска
    5. **Настройте лимит сообщений** для извлечения из каждой группы
    6. **Нажмите "Извлечь посты"** и дождитесь завершения обработки
    
    ### 📊 Функции:
    
    - Поиск по нескольким группам Telegram
    - Балансировка нагрузки на несколько аккаунтов
    - Отображение результатов в удобной таблице
    - Аналитика и визуализация найденных данных
    - Экспорт результатов в Excel или CSV
    
    ### ⚠️ Примечание о ограничениях Telegram API:
    
    Telegram имеет ограничения на частоту запросов. Используйте несколько аккаунтов для обхода этих ограничений при работе с большим количеством групп.
    """)
    
    st.info("ℹ️ Начните работу, введя необходимую информацию в боковой панели слева и нажав кнопку 'Извлечь посты'.")                    