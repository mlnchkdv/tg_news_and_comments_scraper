# app.py
import streamlit as st
import pandas as pd
import asyncio
import time
import re
import os
from datetime import datetime, timedelta
from telethon.sync import TelegramClient
from telethon import functions, types
from telethon.tl.functions.messages import GetHistoryRequest
from telethon.errors import SessionPasswordNeededError, FloodWaitError
from io import BytesIO

# Настройка заголовка страницы
st.set_page_config(
    page_title="Поиск сообщений Telegram",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Инициализация состояния сессии для аккаунтов и настроек
if 'accounts' not in st.session_state:
    st.session_state.accounts = [{
        'api_id': '',
        'api_hash': '',
        'phone': '',
        'password': ''
    }]

if 'settings' not in st.session_state:
    st.session_state.settings = {
        'request_delay': 2.0,
        'request_batch_size': 100,
        'date_from': None,
        'date_to': None,
        'use_date_filter': False
    }

# Инициализация рабочей директории для сессий Telegram
SESSION_DIR = 'telegram_sessions'
os.makedirs(SESSION_DIR, exist_ok=True)

# Функция для получения сущности (канала/группы) по ссылке
async def get_entity(client, group_link):
    try:
        if group_link.startswith('@'):
            return await client.get_entity(group_link)
        elif 'joinchat' in group_link or '+' in group_link:
            # Извлечение хэша из ссылки-приглашения
            invite_hash = group_link.split('/')[-1]
            return await client(functions.messages.ImportChatInviteRequest(invite_hash))
        else:
            # Для обычных публичных каналов и групп
            username = group_link.split('/')[-1]
            return await client.get_entity(username)
    except Exception as e:
        st.error(f"Ошибка при получении информации о группе {group_link}: {str(e)}")
        return None

# Функция создания и подключения клиента Telegram
async def create_client(account, session_path):
    client = TelegramClient(session_path, account['api_id'], account['api_hash'])
    await client.connect()
    
    if not await client.is_user_authorized():
        await client.send_code_request(account['phone'])
        verification_code = st.text_input(f"Введите код подтверждения для {account['phone']}", key=f"code_{account['phone']}")
        
        if verification_code:
            try:
                await client.sign_in(account['phone'], verification_code)
            except SessionPasswordNeededError:
                if account['password']:
                    await client.sign_in(password=account['password'])
                else:
                    st.error(f"Требуется двухфакторная аутентификация для {account['phone']}. Пожалуйста, введите пароль в настройках аккаунта.")
                    return None
    
    return client

# Функция для основного процесса извлечения данных
async def run_extraction(group_links, keyword, max_messages, progress_bar, progress_text, error_container):
    active_accounts = [acc for acc in st.session_state.accounts if acc['api_id'] and acc['api_hash'] and acc['phone']]
    
    if not active_accounts:
        error_container.error("Пожалуйста, добавьте хотя бы один аккаунт Telegram API")
        return None
    
    # Разделение списка групп
    group_list = [link.strip() for link in group_links.split('\n') if link.strip()]
    
    if not group_list:
        error_container.error("Пожалуйста, введите хотя бы одну ссылку на группу")
        return None
    
    # Создание клиентов для всех аккаунтов
    clients = []
    for idx, account in enumerate(active_accounts):
        session_path = os.path.join(SESSION_DIR, f"session_{account['phone']}")
        client = await create_client(account, session_path)
        if client:
            clients.append(client)
    
    if not clients:
        error_container.error("Не удалось подключиться ни к одному аккаунту Telegram")
        return None
    
    # Функция для распределения групп между клиентами
    def distribute_groups(groups, client_count):
        result = [[] for _ in range(client_count)]
        for i, group in enumerate(groups):
            result[i % client_count].append(group)
        return result
    
    # Распределение групп между клиентами
    distributed_groups = distribute_groups(group_list, len(clients))
    
    # Общее количество прогресса (группы * примерное количество сообщений)
    total_progress = len(group_list) * (max_messages if max_messages > 0 else 1000)
    progress_count = 0
    
    # Функция обновления прогресса
    def update_progress(increment=1):
        nonlocal progress_count
        progress_count += increment
        progress_value = min(progress_count / total_progress, 1.0)
        progress_bar.progress(progress_value)
    
    all_results = []
    
    async def process_group(group_link, client_index):
        client = clients[client_index]
        
        try:
            # Подключение к каналу/группе
            entity = await get_entity(client, group_link)
            
            if entity:
                group_name = getattr(entity, 'title', 'Неизвестная группа')
                group_messages = []
                offset_id = 0
                total_messages = 0
                batch_size = st.session_state.settings['request_batch_size']
                
                # Фильтр по дате
                date_filter = None
                if st.session_state.settings['use_date_filter']:
                    # Преобразование объектов даты в datetime с временем в начале/конце дня
                    from_date = datetime.combine(st.session_state.settings['date_from'], datetime.min.time())
                    to_date = datetime.combine(st.session_state.settings['date_to'], datetime.max.time())
                    date_filter = lambda msg: from_date <= msg.date.replace(tzinfo=None) <= to_date
                
                # Получение сообщений с установленным размером пакета
                while True:
                    progress_text.text(f"Обработка группы '{group_name}': проверено {total_messages} сообщений")
                    
                    try:
                        messages = await client(GetHistoryRequest(
                            peer=entity,
                            offset_id=offset_id,
                            offset_date=None,
                            add_offset=0,
                            limit=batch_size,
                            max_id=0,
                            min_id=0,
                            hash=0
                        ))
                    except FloodWaitError as e:
                        wait_time = e.seconds
                        error_container.warning(f"Аккаунт {client_index+1} получил FloodWaitError. Ожидание {wait_time} секунд...")
                        await asyncio.sleep(wait_time)
                        continue
                    
                    if not messages.messages:
                        break
                    
                    # Применение фильтра по дате, если включен
                    filtered_messages = messages.messages
                    if date_filter:
                        filtered_messages = [msg for msg in messages.messages if date_filter(msg)]
                    
                    # Обработка сообщений
                    for message in filtered_messages:
                        total_messages += 1
                        
                        # Обновление индикаторов прогресса
                        update_progress()
                        
                        if max_messages > 0 and total_messages > max_messages:
                            break
                        
                        if hasattr(message, 'message') and message.message:
                            message_text = message.message.lower()
                            if keyword.lower() in message_text:
                                # Получение информации о сообщении
                                sender = "Неизвестно"
                                if hasattr(message, 'from_id') and message.from_id:
                                    try:
                                        sender_entity = await client.get_entity(message.from_id)
                                        sender = getattr(sender_entity, 'first_name', '') or ''
                                        if hasattr(sender_entity, 'last_name') and sender_entity.last_name:
                                            sender += ' ' + sender_entity.last_name
                                        if hasattr(sender_entity, 'username') and sender_entity.username:
                                            sender += f" (@{sender_entity.username})"
                                    except:
                                        sender = "Неизвестно"
                                
                                # Создание URL для сообщения, если это возможно
                                message_url = ""
                                if hasattr(entity, 'username') and entity.username:
                                    message_url = f"https://t.me/{entity.username}/{message.id}"
                                
                                group_messages.append({
                                    'Группа': group_name,
                                    'Ссылка на группу': group_link,
                                    'Отправитель': sender,
                                    'Дата': message.date.strftime('%Y-%m-%d %H:%M:%S'),
                                    'Текст': message.message,
                                    'Ссылка на сообщение': message_url
                                })
                    
                    # Добавление задержки между пакетами для избежания ограничений API
                    await asyncio.sleep(st.session_state.settings['request_delay'])
                    
                    # Установка смещения для следующей итерации
                    if messages.messages:
                        offset_id = messages.messages[-1].id
                    
                    # Проверка, достигли ли мы максимального количества сообщений
                    if max_messages > 0 and total_messages >= max_messages:
                        break
                
                return group_messages
                
            else:
                error_container.error(f"Не удалось получить доступ к группе: {group_link}")
                return []
                
        except Exception as e:
            error_container.error(f"Ошибка при обработке группы {group_link}: {str(e)}")
            return []
    
    # Создание и запуск задач для каждой группы
    tasks = []
    for client_idx, client_groups in enumerate(distributed_groups):
        for group in client_groups:
            tasks.append(process_group(group, client_idx))
    
    # Запуск всех задач параллельно
    group_results = await asyncio.gather(*tasks)
    
    # Объединение результатов
    for result in group_results:
        all_results.extend(result)
    
    # Закрытие всех клиентов
    for client in clients:
        await client.disconnect()
    
    return all_results

# Боковая панель для учетных данных API и настроек
with st.sidebar:
    st.title("Учетные данные API")
    
    # Отображение аккаунтов
    accounts_to_remove = []
    
    for idx, account in enumerate(st.session_state.accounts):
        with st.expander(f"Аккаунт {idx + 1}", expanded=(idx == 0)):
            api_id = st.text_input(f"API ID #{idx + 1}", value=account['api_id'], key=f"api_id_{idx}")
            api_hash = st.text_input(f"API Hash #{idx + 1}", value=account['api_hash'], key=f"api_hash_{idx}", type="password")
            phone = st.text_input(f"Телефон #{idx + 1}", value=account['phone'], key=f"phone_{idx}", 
                                help="Включая код страны (например, +79123456789)")
            password = st.text_input(f"Пароль 2FA #{idx + 1} (если включено)", value=account['password'], 
                                    key=f"password_{idx}", type="password")
            
            # Обновление состояния сессии
            st.session_state.accounts[idx]['api_id'] = api_id
            st.session_state.accounts[idx]['api_hash'] = api_hash
            st.session_state.accounts[idx]['phone'] = phone
            st.session_state.accounts[idx]['password'] = password
            
            if idx > 0 and st.button(f"Удалить аккаунт #{idx + 1}", key=f"remove_{idx}"):
                accounts_to_remove.append(idx)
    
    # Удаление аккаунтов, отмеченных для удаления (в обратном порядке, чтобы избежать проблем с индексами)
    for idx in sorted(accounts_to_remove, reverse=True):
        st.session_state.accounts.pop(idx)
    
    # Кнопка добавления аккаунта
    if st.button("Добавить еще аккаунт"):
        st.session_state.accounts.append({
            'api_id': '',
            'api_hash': '',
            'phone': '',
            'password': ''
        })
        st.experimental_rerun()
    
    # Настройки защиты от бана и ограничения скорости
    st.title("Настройки защиты API")
    with st.expander("Настройки ограничения запросов", expanded=True):
        st.session_state.settings['request_delay'] = st.slider(
            "Задержка между запросами (секунды)", 
            min_value=1.0, 
            max_value=10.0, 
            value=st.session_state.settings['request_delay'],
            step=0.5,
            help="Увеличьте это значение, чтобы снизить риск бана"
        )
        
        st.session_state.settings['request_batch_size'] = st.slider(
            "Сообщений в пакете", 
            min_value=50, 
            max_value=500, 
            value=st.session_state.settings['request_batch_size'],
            step=50,
            help="Количество сообщений, запрашиваемых в каждом пакете. Меньшие значения снижают нагрузку, но увеличивают время обработки."
        )
        
        st.info("⚠️ Более высокие значения задержки и меньшие размеры пакетов снижают риск блокировки, но делают поиск медленнее.")

# Основной раздел для параметров поиска
st.title("🔍 Поиск сообщений в группах Telegram")

# Текстовая область для ссылок на группы
group_links = st.text_area(
    "Ссылки на группы Telegram (по одной в строке)",
    help="Введите полные ссылки на группы или каналы (например, https://t.me/groupname)"
)

# Фильтрация сообщений
col1, col2 = st.columns(2)

with col1:
    keyword = st.text_input("Ключевое слово для поиска", 
                           help="Поиск сообщений, содержащих это ключевое слово")
    
    max_messages = st.number_input(
        "Максимальное количество сообщений для проверки (0 = без ограничений)",
        min_value=0,
        value=1000,
        step=100,
        help="Ограничивает количество проверяемых сообщений для каждой группы"
    )

with col2:
    # Фильтр по дате
    st.session_state.settings['use_date_filter'] = st.checkbox(
        "Фильтр по дате", 
        value=st.session_state.settings['use_date_filter'],
        help="Включить поиск сообщений только в указанном диапазоне дат"
    )
    
    if st.session_state.settings['use_date_filter']:
        date_col1, date_col2 = st.columns(2)
        
        with date_col1:
            st.session_state.settings['date_from'] = st.date_input(
                "Дата с", 
                value=st.session_state.settings['date_from'],
                help="Начальная дата для поиска"
            )
        
        with date_col2:
            st.session_state.settings['date_to'] = st.date_input(
                "Дата по", 
                value=st.session_state.settings['date_to'],
                help="Конечная дата для поиска"
            )

# Раздел для отображения ошибок
error_container = st.empty()

# Кнопка для запуска процесса поиска
if st.button("Найти сообщения"):
    if not group_links.strip():
        error_container.error("Пожалуйста, введите ссылки на группы")
    elif not keyword.strip():
        error_container.error("Пожалуйста, введите ключевое слово для поиска")
    else:
        # Создание индикаторов прогресса
        progress_text = st.empty()
        progress_bar = st.progress(0)
        progress_text.text("Подключение к Telegram API...")
        
        # Запуск процесса поиска
        results = asyncio.run(run_extraction(group_links, keyword, max_messages, 
                                            progress_bar, progress_text, error_container))
        
        if results:
            # Показать результаты
            st.subheader(f"Найдено {len(results)} сообщений")
            
            # Преобразование результатов в DataFrame
            results_df = pd.DataFrame(results)
            
            # Отображение результатов в таблице
            st.dataframe(results_df)
            
            # Экспорт в CSV и Excel
            st.download_button(
                label="Скачать в формате CSV",
                data=results_df.to_csv(index=False).encode('utf-8'),
                file_name=f"telegram_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )
            
            # Экспорт в Excel
            excel_buffer = BytesIO()
            results_df.to_excel(excel_buffer, index=False)
            excel_data = excel_buffer.getvalue()
            
            st.download_button(
                label="Скачать в формате Excel",
                data=excel_data,
                file_name=f"telegram_search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.ms-excel"
            )
            
        else:
            if error_container.empty:
                error_container.warning("Не найдено сообщений или возникла ошибка при выполнении поиска.")
        
        # Сброс индикаторов прогресса
        progress_bar.empty()
        progress_text.empty()

# Отображение информации о приложении
with st.expander("О приложении"):
    st.markdown("""
    ## Поиск сообщений в группах Telegram
    
    Это приложение позволяет выполнять поиск сообщений в группах и каналах Telegram по ключевым словам.
    
    ### Как использовать:
    1. Введите данные API Telegram в боковой панели (получите их на [https://my.telegram.org/apps](https://my.telegram.org/apps))
    2. Укажите ссылки на группы или каналы, в которых нужно выполнить поиск
    3. Введите ключевое слово для поиска
    4. Настройте дополнительные параметры, если необходимо
    5. Нажмите кнопку "Найти сообщения"
    
    ### Важные примечания:
    - При частом использовании Telegram может ограничить ваш аккаунт на определенное время
    - Используйте разумные задержки в настройках, чтобы избежать блокировок
    - Добавление нескольких аккаунтов повышает скорость и надежность работы
    """)