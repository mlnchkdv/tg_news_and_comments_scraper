import streamlit as st
import pandas as pd
import numpy as np
import asyncio
import telethon
from telethon.sync import TelegramClient
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.errors import UsernameNotOccupiedError
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go
import re
import json
import os
import time
from io import BytesIO
import base64

# Настройка страницы Streamlit
st.set_page_config(
    page_title="Telegram Group Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Инициализация сессии состояния
if 'settings' not in st.session_state:
    st.session_state.settings = {}
if 'extra_accounts' not in st.session_state:
    st.session_state.extra_accounts = []
if 'login_complete' not in st.session_state:
    st.session_state.login_complete = False

# Главная функция для работы с Telegram API
async def get_group_entity(client, group_link, error_container):
    """Получение информации о группе по ссылке"""
    try:
        # Извлечение имени группы из ссылки
        if 'https://t.me/' in group_link:
            group_name = group_link.split('https://t.me/')[1].strip()
        elif 't.me/' in group_link:
            group_name = group_link.split('t.me/')[1].strip()
        else:
            group_name = group_link.strip()
        
        # Удаление лишних символов из названия группы
        group_name = group_name.rstrip('/')
        
        try:
            # Попытка получить информацию о группе
            return await client.get_entity(group_name)
        except (ValueError, UsernameNotOccupiedError):
            # Если не удалось по имени, пробуем по полной ссылке
            return await client.get_entity(group_link)
        except telethon.errors.rpcerrorlist.UsernameInvalidError:
            error_container.error(f"Недопустимое имя пользователя: {group_name}")
            return None
        except telethon.errors.rpcerrorlist.KeyUnregisteredError:
            error_container.error(
                "Ошибка API: Ключ не зарегистрирован в системе. "
                "Пожалуйста, убедитесь, что вы правильно настроили API ключи и они активированы. "
                "Активация ключей может занять до 24 часов после их создания."
            )
            return None
    except Exception as e:
        error_container.error(f"Ошибка при получении информации о группе {group_link}: {str(e)}")
        return None

async def create_client(api_id, api_hash, phone, error_container):
    """Создание клиента Telegram с обработкой ошибок"""
    if not api_id or not api_hash or not phone:
        error_container.error("Необходимо указать API ID, API Hash и номер телефона")
        return None
    
    try:
        # Создание клиента
        client = TelegramClient(f"session_{phone}", api_id, api_hash)
        
        # Попытка подключения
        await client.connect()
        
        # Проверка авторизации
        if not await client.is_user_authorized():
            # Запрос кода авторизации
            try:
                await client.send_code_request(phone)
                error_container.warning(f"Для авторизации аккаунта {phone} введите код, отправленный вам в Telegram:")
                code = error_container.text_input(f"Код авторизации для {phone}")
                
                if code:
                    try:
                        await client.sign_in(phone, code)
                        error_container.success(f"Аккаунт {phone} успешно авторизован!")
                    except telethon.errors.rpcerrorlist.SessionPasswordNeededError:
                        # Если включена двухфакторная аутентификация
                        password = error_container.text_input(f"Введите пароль двухфакторной аутентификации для {phone}", type="password")
                        if password:
                            await client.sign_in(password=password)
                            error_container.success(f"Аккаунт {phone} успешно авторизован!")
            except telethon.errors.rpcerrorlist.FloodWaitError as e:
                wait_time = e.seconds
                error_container.error(f"Слишком много попыток! Пожалуйста, подождите {wait_time} секунд перед новой попыткой.")
                await client.disconnect()
                return None
            except telethon.errors.rpcerrorlist.PhoneNumberInvalidError:
                error_container.error(f"Номер телефона {phone} недействителен. Проверьте формат: +79123456789")
                await client.disconnect()
                return None
            except telethon.errors.rpcerrorlist.ApiIdInvalidError:
                error_container.error("API ID или API Hash недействительны. Проверьте настройки.")
                await client.disconnect()
                return None
        
        return client
    except telethon.errors.rpcerrorlist.KeyUnregisteredError:
        error_container.error(
            "Ключ не зарегистрирован в системе. Убедитесь, что ваши API ключи активированы. "
            "Это может занять до 24 часов после создания."
        )
        return None
    except Exception as e:
        error_container.error(f"Ошибка при создании клиента Telegram: {str(e)}")
        return None

async def get_group_info(client, group_entity, error_container):
    """Получение подробной информации о группе"""
    try:
        if hasattr(group_entity, 'username') and group_entity.username:
            full_info = await client(GetFullChannelRequest(group_entity.username))
        else:
            full_info = await client(GetFullChannelRequest(group_entity.id))
        
        return {
            'id': group_entity.id,
            'title': group_entity.title,
            'username': getattr(group_entity, 'username', None),
            'participants_count': full_info.full_chat.participants_count,
            'about': full_info.full_chat.about,
            'is_channel': isinstance(group_entity, telethon.tl.types.Channel),
            'is_group': isinstance(group_entity, telethon.tl.types.Channel) and getattr(group_entity, 'megagroup', False),
            'date': getattr(group_entity, 'date', None),
            'photo': getattr(group_entity, 'photo', None) != None
        }
    except Exception as e:
        error_container.error(f"Ошибка при получении информации о группе: {str(e)}")
        return None

async def get_messages_stats(client, group_entity, days_count, error_container, progress_bar=None):
    """Получение статистики сообщений группы"""
    try:
        # Определение временного промежутка
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_count)
        
        # Структуры для сбора статистики
        messages_per_day = {}
        top_users = {}
        top_users_by_reactions = {}
        reactions_per_day = {}
        views_per_day = {}
        forwards_per_day = {}
        replies_per_day = {}
        total_messages = 0
        total_views = 0
        
        # Инициализация дней для статистики
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            messages_per_day[date_str] = 0
            reactions_per_day[date_str] = 0
            views_per_day[date_str] = 0
            forwards_per_day[date_str] = 0
            replies_per_day[date_str] = 0
            current_date += timedelta(days=1)
        
        # Получение сообщений
        async for message in client.iter_messages(group_entity, offset_date=end_date, limit=None):
            # Проверка, находится ли сообщение в нужном временном диапазоне
            if message.date < start_date:
                break
            
            # Обновление счетчика общего количества сообщений
            total_messages += 1
            
            # Обновление прогресса (если есть прогресс-бар)
            if progress_bar is not None:
                progress_bar.progress((end_date - message.date).total_seconds() / (end_date - start_date).total_seconds())
            
            # Обновление статистики по дням
            date_str = message.date.strftime('%Y-%m-%d')
            messages_per_day[date_str] = messages_per_day.get(date_str, 0) + 1
            
            # Статистика просмотров
            if hasattr(message, 'views') and message.views:
                views_per_day[date_str] = views_per_day.get(date_str, 0) + message.views
                total_views += message.views
            
            # Статистика пересылок
            if hasattr(message, 'forwards') and message.forwards:
                forwards_per_day[date_str] = forwards_per_day.get(date_str, 0) + message.forwards
            
            # Статистика ответов
            if message.replies:
                replies_per_day[date_str] = replies_per_day.get(date_str, 0) + message.replies.replies
            
            # Статистика по пользователям
            if message.sender_id:
                sender_id = message.sender_id
                if sender_id not in top_users:
                    try:
                        sender = await client.get_entity(sender_id)
                        sender_name = getattr(sender, 'first_name', '') + ' ' + getattr(sender, 'last_name', '')
                        if not sender_name.strip():
                            sender_name = getattr(sender, 'title', str(sender_id))
                    except:
                        sender_name = str(sender_id)
                    
                    top_users[sender_id] = {
                        'name': sender_name,
                        'count': 0,
                        'views': 0,
                        'reactions': 0
                    }
                
                top_users[sender_id]['count'] += 1
                
                if hasattr(message, 'views') and message.views:
                    top_users[sender_id]['views'] += message.views
            
            # Статистика реакций
            if hasattr(message, 'reactions') and message.reactions:
                reaction_count = sum(reaction.count for reaction in message.reactions.results)
                reactions_per_day[date_str] = reactions_per_day.get(date_str, 0) + reaction_count
                
                if message.sender_id:
                    top_users[message.sender_id]['reactions'] += reaction_count
        
        # Сортировка топ пользователей по количеству сообщений
        sorted_users = sorted(top_users.items(), key=lambda x: x[1]['count'], reverse=True)
        
        # Сортировка топ пользователей по количеству реакций
        sorted_users_by_reactions = sorted(top_users.items(), key=lambda x: x[1]['reactions'], reverse=True)
        
        # Подготовка данных для графиков
        dates = list(messages_per_day.keys())
        messages_count = list(messages_per_day.values())
        reactions_count = [reactions_per_day.get(date, 0) for date in dates]
        views_count = [views_per_day.get(date, 0) for date in dates]
        forwards_count = [forwards_per_day.get(date, 0) for date in dates]
        replies_count = [replies_per_day.get(date, 0) for date in dates]
        
        return {
            'total_messages': total_messages,
            'total_views': total_views,
            'messages_per_day': {'dates': dates, 'values': messages_count},
            'reactions_per_day': {'dates': dates, 'values': reactions_count},
            'views_per_day': {'dates': dates, 'values': views_count},
            'forwards_per_day': {'dates': dates, 'values': forwards_count},
            'replies_per_day': {'dates': dates, 'values': replies_count},
            'top_users': sorted_users[:10],  # Топ-10 пользователей по сообщениям
            'top_users_by_reactions': sorted_users_by_reactions[:10]  # Топ-10 пользователей по реакциям
        }
    except Exception as e:
        error_container.error(f"Ошибка при получении статистики сообщений: {str(e)}")
        return None

def render_group_info(group_info):
    """Отображение информации о группе"""
    st.subheader("Информация о группе")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Название:** {group_info['title']}")
        st.markdown(f"**ID:** {group_info['id']}")
        if group_info['username']:
            st.markdown(f"**Имя пользователя:** @{group_info['username']}")
        st.markdown(f"**Количество участников:** {group_info['participants_count']:,}")
    
    with col2:
        group_type = "Канал" if not group_info['is_group'] else "Группа"
        st.markdown(f"**Тип:** {group_type}")
        if group_info['date']:
            st.markdown(f"**Дата создания:** {group_info['date'].strftime('%Y-%m-%d')}")
        st.markdown(f"**Фото профиля:** {'Есть' if group_info['photo'] else 'Нет'}")
    
    if group_info['about']:
        st.markdown("**Описание:**")
        st.markdown(f"_{group_info['about']}_")

def render_message_stats(stats, days_count):
    """Отображение статистики сообщений"""
    if not stats:
        st.warning("Нет данных для отображения")
        return
    
    st.subheader("Статистика активности")
    
    # Основные метрики
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Всего сообщений", f"{stats['total_messages']:,}")
    with col2:
        avg_messages = stats['total_messages'] / days_count if days_count > 0 else 0
        st.metric("Среднее кол-во сообщений в день", f"{avg_messages:.1f}")
    with col3:
        st.metric("Всего просмотров", f"{stats['total_views']:,}")
    
    # График сообщений по дням
    st.subheader("Активность по дням")
    
    fig, ax = plt.subplots(figsize=(10, 6))
    dates = [datetime.strptime(date, '%Y-%m-%d').date() for date in stats['messages_per_day']['dates']]
    ax.plot(dates, stats['messages_per_day']['values'], marker='o', linestyle='-', color='#1f77b4', label='Сообщения')
    
    ax.set_xlabel('Дата')
    ax.set_ylabel('Количество сообщений')
    ax.grid(True, linestyle='--', alpha=0.7)
    ax.set_title('Количество сообщений по дням')
    
    # Форматирование дат на оси X
    plt.xticks(rotation=45)
    fig.tight_layout()
    
    st.pyplot(fig)
    
    # График просмотров по дням
    if any(stats['views_per_day']['values']):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(dates, stats['views_per_day']['values'], marker='o', linestyle='-', color='#ff7f0e', label='Просмотры')
        
        ax.set_xlabel('Дата')
        ax.set_ylabel('Количество просмотров')
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_title('Количество просмотров по дням')
        
        plt.xticks(rotation=45)
        fig.tight_layout()
        
        st.pyplot(fig)
    
    # График реакций по дням
    if any(stats['reactions_per_day']['values']):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(dates, stats['reactions_per_day']['values'], marker='o', linestyle='-', color='#2ca02c', label='Реакции')
        
        ax.set_xlabel('Дата')
        ax.set_ylabel('Количество реакций')
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_title('Количество реакций по дням')
        
        plt.xticks(rotation=45)
        fig.tight_layout()
        
        st.pyplot(fig)
    
    # График ответов по дням
    if any(stats['replies_per_day']['values']):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.plot(dates, stats['replies_per_day']['values'], marker='o', linestyle='-', color='#d62728', label='Ответы')
        
        ax.set_xlabel('Дата')
        ax.set_ylabel('Количество ответов')
        ax.grid(True, linestyle='--', alpha=0.7)
        ax.set_title('Количество ответов по дням')
        
        plt.xticks(rotation=45)
        fig.tight_layout()
        
        st.pyplot(fig)
    
    # Топ пользователей по сообщениям
    st.subheader("Топ пользователей по количеству сообщений")
    
    if stats['top_users']:
        top_users_data = [(user[1]['name'], user[1]['count']) for user in stats['top_users']]
        top_users_df = pd.DataFrame(top_users_data, columns=['Пользователь', 'Сообщения'])
        
        fig, ax = plt.subplots(figsize=(10, 6))
        bars = ax.bar(top_users_df['Пользователь'], top_users_df['Сообщения'], color='#1f77b4')
        
        ax.set_xlabel('Пользователь')
        ax.set_ylabel('Количество сообщений')
        ax.set_title('Топ пользователей по количеству сообщений')
        
        # Поворот подписей на оси X для лучшей читаемости
        plt.xticks(rotation=45, ha='right')
        
        # Добавление значений над столбцами
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                    f'{int(height)}', ha='center', va='bottom')
        
        fig.tight_layout()
        
        st.pyplot(fig)
        
        # Таблица с данными
        st.dataframe(top_users_df)
    else:
        st.info("Нет данных о сообщениях пользователей")
    
    # Топ пользователей по реакциям
    if any(user[1]['reactions'] for user in stats['top_users_by_reactions']):
        st.subheader("Топ пользователей по полученным реакциям")
        
        top_users_reactions_data = [(user[1]['name'], user[1]['reactions']) for user in stats['top_users_by_reactions'] if user[1]['reactions'] > 0]
        if top_users_reactions_data:
            top_users_reactions_df = pd.DataFrame(top_users_reactions_data, columns=['Пользователь', 'Реакции'])
            
            fig, ax = plt.subplots(figsize=(10, 6))
            bars = ax.bar(top_users_reactions_df['Пользователь'], top_users_reactions_df['Реакции'], color='#2ca02c')
            
            ax.set_xlabel('Пользователь')
            ax.set_ylabel('Количество реакций')
            ax.set_title('Топ пользователей по полученным реакциям')
            
            plt.xticks(rotation=45, ha='right')
            
            for bar in bars:
                height = bar.get_height()
                ax.text(bar.get_x() + bar.get_width()/2., height + 0.1,
                        f'{int(height)}', ha='center', va='bottom')
            
            fig.tight_layout()
            
            st.pyplot(fig)
            
            st.dataframe(top_users_reactions_df)
        else:
            st.info("Нет данных о реакциях на сообщения пользователей")

async def main():
    st.set_page_config(
        page_title="Анализатор Telegram-групп",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("📊 Анализатор Telegram-групп")
    st.markdown("""
    Этот инструмент позволяет получить подробную статистику о Telegram-группах и каналах.
    Введите ссылку на группу и настройте параметры анализа.
    """)
    
    # Контейнер для сообщений об ошибках
    error_container = st.empty()
    
    # Боковая панель с настройками и авторизацией
    with st.sidebar:
        st.header("Настройки")
        
        st.subheader("API настройки")
        api_id = st.text_input("API ID", help="API ID от my.telegram.org")
        api_hash = st.text_input("API Hash", help="API Hash от my.telegram.org", type="password")
        phone = st.text_input("Номер телефона", help="Номер телефона с кодом страны, например +79123456789")
        
        st.subheader("Параметры анализа")
        days_count = st.slider("Количество дней для анализа", 1, 30, 7, help="За какой период анализировать сообщения")
        
        st.markdown("---")
        st.markdown("### О приложении")
        st.markdown("""
        Анализатор групп Telegram позволяет получить подробную статистику по активности в группах и каналах.
        
        **Как использовать:**
        1. Введите свои API данные (получить на [my.telegram.org](https://my.telegram.org))
        2. Укажите ссылку на группу для анализа
        3. Настройте период анализа
        4. Нажмите "Начать анализ"
        
        **Примечание:** Приложение работает локально, ваши данные не передаются третьим лицам.
        """)
    
    # Основная часть - ввод ссылки и отображение результатов
    group_link = st.text_input("Введите ссылку на группу или канал Telegram", help="Например, https://t.me/group_name или @group_name")
    
    analyze_button = st.button("Начать анализ", type="primary")
    
    if analyze_button and group_link:
        with st.spinner("Подключение к Telegram API..."):
            # Создание клиента
            client = await create_client(api_id, api_hash, phone, error_container)
            
            if client is not None and await client.is_user_authorized():
                with st.spinner("Получение информации о группе..."):
                    # Получение информации о группе
                    group_entity = await get_group_entity(client, group_link, error_container)
                    
                    if group_entity:
                        # Получение подробной информации о группе
                        group_info = await get_group_info(client, group_entity, error_container)
                        
                        if group_info:
                            # Отображение информации о группе
                            render_group_info(group_info)
                            
                            # Сбор статистики сообщений
                            with st.spinner(f"Анализ сообщений за последние {days_count} дней..."):
                                progress_bar = st.progress(0)
                                message_stats = await get_messages_stats(client, group_entity, days_count, error_container, progress_bar)
                                progress_bar.empty()
                            
                            # Отображение статистики сообщений
                            if message_stats:
                                render_message_stats(message_stats, days_count)
                            else:
                                st.warning("Не удалось получить статистику сообщений")
                        
                # Закрытие клиента
                await client.disconnect()
    
    # Пустой запуск без нажатия кнопки
    elif not analyze_button and group_link:
        st.info("Нажмите 'Начать анализ' для получения информации о группе")
    elif analyze_button and not group_link:
        st.warning("Пожалуйста, введите ссылку на группу или канал")

if __name__ == "__main__":
    import asyncio
    import telethon
    from telethon import TelegramClient
    from telethon.tl.functions.channels import GetFullChannelRequest
    import pandas as pd
    import streamlit as st
    import matplotlib.pyplot as plt
    import re
    from datetime import datetime, timedelta
    
    # Настройка русской локали для matplotlib
    import matplotlib as mpl
    mpl.rcParams['font.family'] = 'DejaVu Sans'
    
    # Запуск асинхронного main
    asyncio.run(main())