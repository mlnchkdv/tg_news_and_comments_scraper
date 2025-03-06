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

async def create_client(api_id, api_hash, phone, error_container):
    """Создание клиента Telegram API с обработкой ошибок"""
    if not api_id or not api_hash or not phone:
        error_container.error("Пожалуйста, заполните все поля API настроек")
        return None
    
    try:
        # Создание клиента
        client = TelegramClient('session_name', int(api_id), api_hash)
        await client.connect()
        
        # Проверка авторизации
        if not await client.is_user_authorized():
            try:
                # Отправка кода подтверждения
                sent_code = await client.send_code_request(phone)
                
                # Запрос кода у пользователя
                code = st.text_input("Введите код подтверждения, отправленный в Telegram")
                
                if code:
                    try:
                        # Попытка входа с введенным кодом
                        await client.sign_in(phone, code)
                        st.success("Успешная авторизация!")
                    except telethon.errors.SessionPasswordNeededError:
                        # Если требуется пароль двухфакторной аутентификации
                        password = st.text_input("Введите пароль двухфакторной аутентификации", type="password")
                        if password:
                            await client.sign_in(password=password)
                            st.success("Успешная авторизация с 2FA!")
                        else:
                            error_container.warning("Требуется пароль двухфакторной аутентификации")
                            return None
                    except Exception as e:
                        error_container.error(f"Ошибка при вводе кода: {str(e)}")
                        return None
                else:
                    error_container.info("Введите код подтверждения, отправленный в Telegram")
                    return None
            except telethon.errors.FloodWaitError as e:
                error_container.error(f"Слишком много попыток входа. Подождите {e.seconds} секунд")
                return None
            except telethon.errors.PhoneNumberBannedError:
                error_container.error("Этот номер телефона заблокирован в Telegram")
                return None
            except telethon.errors.PhoneNumberInvalidError:
                error_container.error("Неверный формат номера телефона. Используйте формат +79123456789")
                return None
            except telethon.errors.ApiIdInvalidError:
                error_container.error("Недействительные API ID или API Hash")
                return None
            except Exception as e:
                error_container.error(f"Ошибка при авторизации: {str(e)}")
                return None
        
        return client
    except telethon.errors.ApiIdInvalidError:
        error_container.error("Недействительные API ID или API Hash")
        return None
    except ValueError:
        error_container.error("API ID должен быть числом")
        return None
    except Exception as e:
        error_container.error(f"Ошибка при создании клиента: {str(e)}")
        return None

async def get_group_entity(client, group_link, error_container):
    """Получение entity группы по ссылке"""
    try:
        if not group_link:
            error_container.error("Укажите ссылку на группу или канал")
            return None
        
        # Извлечение имени группы из ссылки
        group_name = None
        if 't.me/' in group_link:
            group_name = group_link.split('t.me/')[1].split('/')[0].split('?')[0]
        elif group_link.startswith('@'):
            group_name = group_link[1:]
        else:
            group_name = group_link
        
        # Удаление + из имени группы (если есть)
        group_name = group_name.replace('+', '')
        
        try:
            # Получение entity группы
            entity = await client.get_entity(group_name)
            return entity
        except telethon.errors.UsernameNotOccupiedError:
            error_container.error(f"Группа или канал с именем {group_name} не существует")
            return None
        except telethon.errors.UsernameInvalidError:
            error_container.error(f"Недопустимое имя пользователя: {group_name}")
            return None
        except telethon.errors.InviteHashInvalidError:
            error_container.error("Недействительный хэш приглашения")
            return None
        except telethon.errors.ChannelPrivateError:
            error_container.error("Этот канал/группа является приватным. Сначала вступите в группу.")
            return None
    except Exception as e:
        error_container.error(f"Ошибка при получении информации о группе: {str(e)}")
        return None

async def get_group_info(client, group_entity, error_container):
    """Получение подробной информации о группе или канале"""
    try:
        if hasattr(group_entity, 'megagroup') or hasattr(group_entity, 'gigagroup') or hasattr(group_entity, 'broadcast'):
            # Это канал или супергруппа
            full_entity = await client(GetFullChannelRequest(channel=group_entity))
            
            # Базовая информация
            info = {
                'title': group_entity.title,
                'username': group_entity.username if hasattr(group_entity, 'username') else "Отсутствует",
                'type': 'Канал' if getattr(group_entity, 'broadcast', False) else 'Супергруппа',
                'id': group_entity.id,
                'members_count': full_entity.full_chat.participants_count if hasattr(full_entity.full_chat, 'participants_count') else "Неизвестно",
                'description': full_entity.full_chat.about if hasattr(full_entity.full_chat, 'about') else "Отсутствует",
                'creation_date': group_entity.date.strftime('%d.%m.%Y %H:%M:%S') if hasattr(group_entity, 'date') else "Неизвестно",
                'verified': getattr(group_entity, 'verified', False),
                'restricted': getattr(group_entity, 'restricted', False),
                'scam': getattr(group_entity, 'scam', False),
                'fake': getattr(group_entity, 'fake', False),
            }
        else:
            # Это обычная группа
            info = {
                'title': group_entity.title if hasattr(group_entity, 'title') else "Неизвестно",
                'username': group_entity.username if hasattr(group_entity, 'username') else "Отсутствует",
                'type': 'Группа',
                'id': group_entity.id,
                'members_count': "Неизвестно", # Для обычных групп требуется отдельный запрос
                'description': "Отсутствует", # Для обычных групп требуется отдельный запрос
                'creation_date': group_entity.date.strftime('%d.%m.%Y %H:%M:%S') if hasattr(group_entity, 'date') else "Неизвестно",
                'verified': getattr(group_entity, 'verified', False),
                'restricted': getattr(group_entity, 'restricted', False),
                'scam': getattr(group_entity, 'scam', False),
                'fake': getattr(group_entity, 'fake', False),
            }
        
        return info
    except telethon.errors.ChannelPrivateError:
        error_container.error("Этот канал/группа является приватным. Сначала вступите в группу.")
        return None
    except Exception as e:
        error_container.error(f"Ошибка при получении информации о группе: {str(e)}")
        return None

def render_group_info(group_info):
    """Отображение информации о группе"""
    st.subheader(f"Информация о группе: {group_info['title']}")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown(f"**Название:** {group_info['title']}")
        st.markdown(f"**Тип:** {group_info['type']}")
        st.markdown(f"**ID:** `{group_info['id']}`")
        st.markdown(f"**Имя пользователя:** @{group_info['username'] if group_info['username'] != 'Отсутствует' else '-'}")
    
    with col2:
        st.markdown(f"**Количество участников:** {group_info['members_count']}")
        st.markdown(f"**Дата создания:** {group_info['creation_date']}")
        
        # Статусы
        statuses = []
        if group_info['verified']:
            statuses.append("✅ Верифицирован")
        if group_info['restricted']:
            statuses.append("⚠️ Имеет ограничения")
        if group_info['scam']:
            statuses.append("🚫 Отмечен как скам")
        if group_info['fake']:
            statuses.append("🚫 Отмечен как фейк")
        
        if statuses:
            st.markdown("**Статусы:** " + ", ".join(statuses))
    
    # Описание
    if group_info['description'] != "Отсутствует":
        st.markdown("**Описание:**")
        st.markdown(f"> {group_info['description']}")

async def get_messages_stats(client, group_entity, days_count, error_container, progress_bar=None):
    """Сбор статистики сообщений"""
    try:
        # Определение временного диапазона
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_count)
        
        # Инициализация статистики
        stats = {
            'total_messages': 0,
            'total_views': 0,
            'total_reactions': 0,
            'total_replies': 0,
            'messages_per_day': {'dates': [], 'values': []},
            'views_per_day': {'dates': [], 'values': []},
            'reactions_per_day': {'dates': [], 'values': []},
            'replies_per_day': {'dates': [], 'values': []},
            'top_users': {},
            'top_users_by_reactions': {}
        }
        
        # Инициализация данных по дням
        current_date = start_date
        while current_date <= end_date:
            date_str = current_date.strftime('%Y-%m-%d')
            stats['messages_per_day']['dates'].append(date_str)
            stats['messages_per_day']['values'].append(0)
            stats['views_per_day']['dates'].append(date_str)
            stats['views_per_day']['values'].append(0)
            stats['reactions_per_day']['dates'].append(date_str)
            stats['reactions_per_day']['values'].append(0)
            stats['replies_per_day']['dates'].append(date_str)
            stats['replies_per_day']['values'].append(0)
            current_date += timedelta(days=1)
        
        # Получение сообщений
        messages_iter = client.iter_messages(
            group_entity,
            offset_date=end_date,
            reverse=True,
            limit=None
        )
        
        # Обработка сообщений
        messages_processed = 0
        async for message in messages_iter:
            # Прекращаем, если вышли за пределы диапазона
            if message.date < start_date:
                continue
            if message.date > end_date:
                break
            
            # Обновление индикатора прогресса
            messages_processed += 1
            if messages_processed % 100 == 0 and progress_bar:
                progress_percent = min(0.99, messages_processed / 1000)  # Предполагаемый максимум - 1000 сообщений
                progress_bar.progress(progress_percent, f"Обработано {messages_processed} сообщений")
            
            # Общая статистика
            stats['total_messages'] += 1
            
            # Просмотры (только для каналов)
            if hasattr(message, 'views') and message.views:
                stats['total_views'] += message.views
            
            # Реакции
            reactions_count = 0
            if hasattr(message, 'reactions') and message.reactions:
                for reaction in message.reactions.results:
                    reactions_count += reaction.count
                stats['total_reactions'] += reactions_count
            
            # Ответы
            if hasattr(message, 'replies') and message.replies:
                stats['total_replies'] += message.replies.replies
            
            # Статистика по дням
            msg_date = message.date.strftime('%Y-%m-%d')
            day_index = stats['messages_per_day']['dates'].index(msg_date) if msg_date in stats['messages_per_day']['dates'] else -1
            
            if day_index >= 0:
                stats['messages_per_day']['values'][day_index] += 1
                
                if hasattr(message, 'views') and message.views:
                    stats['views_per_day']['values'][day_index] += message.views
                
                if reactions_count > 0:
                    stats['reactions_per_day']['values'][day_index] += reactions_count
                
                if hasattr(message, 'replies') and message.replies:
                    stats['replies_per_day']['values'][day_index] += message.replies.replies
            
            # Статистика по пользователям
            if message.sender_id:
                sender_id = str(message.sender_id)
                
                # Добавляем пользователя, если его нет в статистике
                if sender_id not in stats['top_users']:
                    try:
                        sender = await message.get_sender()
                        sender_name = sender.first_name
                        if hasattr(sender, 'last_name') and sender.last_name:
                            sender_name += f" {sender.last_name}"
                        if hasattr(sender, 'username') and sender.username:
                            sender_name += f" (@{sender.username})"
                    except:
                        sender_name = f"User {sender_id}"
                    
                    stats['top_users'][sender_id] = {
                        'name': sender_name,
                        'count': 0
                    }
                    
                    stats['top_users_by_reactions'][sender_id] = {
                        'name': sender_name,
                        'reactions': 0
                    }
                
                # Увеличиваем счетчики
                stats['top_users'][sender_id]['count'] += 1
                
                if reactions_count > 0:
                    stats['top_users_by_reactions'][sender_id]['reactions'] += reactions_count
        
        # Сортировка пользователей
        stats['top_users'] = {k: v for k, v in sorted(
            stats['top_users'].items(), 
            key=lambda item: item[1]['count'], 
            reverse=True
        )}
        
        stats['top_users_by_reactions'] = {k: v for k, v in sorted(
            stats['top_users_by_reactions'].items(), 
            key=lambda item: item[1]['reactions'], 
            reverse=True
        )}
        
        if progress_bar:
            progress_bar.progress(1.0, "Сбор статистики завершен!")
        
        return stats
    except Exception as e:
        error_container.error(f"Ошибка при сборе статистики сообщений: {str(e)}")
        return None

def render_message_stats(stats):
    """Отображение статистики сообщений"""
    st.subheader("Общая статистика")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Всего сообщений", stats['total_messages'])
    
    with col2:
        st.metric("Всего просмотров", f"{stats['total_views']:,}".replace(',', ' '))
    
    with col3:
        st.metric("Всего реакций", stats['total_reactions'])
    
    with col4:
        st.metric("Всего ответов", stats['total_replies'])
    
    # График сообщений по дням
    st.subheader("Активность по дням")
    
    fig, ax = plt.subplots(figsize=(10, 5))
    
    # Форматируем даты для лучшего отображения
    dates = [datetime.strptime(date, '%Y-%m-%d').strftime('%d.%m') for date in stats['messages_per_day']['dates']]
    
    x = range(len(dates))
    plt.bar(x, stats['messages_per_day']['values'], color='blue', alpha=0.7, label='Сообщения')
    plt.xticks(x, dates, rotation=45)
    plt.xlabel('Дата')
    plt.ylabel('Количество сообщений')
    plt.title('Активность сообщений по дням')
    plt.tight_layout()
    
    st.pyplot(fig)
    
    # График просмотров по дням
    if sum(stats['views_per_day']['values']) > 0:
        st.subheader("Просмотры по дням")
        
        fig, ax = plt.subplots(figsize=(10, 5))
        
        plt.bar(x, stats['views_per_day']['values'], color='green', alpha=0.7, label='Просмотры')
        plt.xticks(x, dates, rotation=45)
        plt.xlabel('Дата')
        plt.ylabel('Количество просмотров')
        plt.title('Просмотры сообщений по дням')
        plt.tight_layout()
        
        st.pyplot(fig)
    
    # График реакций по дням
    if sum(stats['reactions_per_day']['values']) > 0:
        st.subheader("Реакции по дням")
        
        fig, ax = plt.subplots(figsize=(10, 5))
        
        plt.bar(x, stats['reactions_per_day']['values'], color='purple', alpha=0.7, label='Реакции')
        plt.xticks(x, dates, rotation=45)
        plt.xlabel('Дата')
        plt.ylabel('Количество реакций')
        plt.title('Реакции на сообщения по дням')
        plt.tight_layout()
        
        st.pyplot(fig)
    
    # График ответов по дням
    if sum(stats['replies_per_day']['values']) > 0:
        st.subheader("Ответы по дням")
        
        fig, ax = plt.subplots(figsize=(10, 5))
        
        plt.bar(x, stats['replies_per_day']['values'], color='orange', alpha=0.7, label='Ответы')
        plt.xticks(x, dates, rotation=45)
        plt.xlabel('Дата')
        plt.ylabel('Количество ответов')
        plt.title('Ответы на сообщения по дням')
        plt.tight_layout()
        
        st.pyplot(fig)
    
    # Топ пользователей
    if stats['top_users']:
        st.subheader("Топ 10 активных пользователей")
        
        top_10_users = list(stats['top_users'].items())[:10]
        
        user_names = [user[1]['name'] for user in top_10_users]
        user_counts = [user[1]['count'] for user in top_10_users]
        
        fig, ax = plt.subplots(figsize=(10, 6))
        
        plt.barh(range(len(user_names)), user_counts, color='blue', alpha=0.7)
        plt.yticks(range(len(user_names)), user_names)
        plt.xlabel('Количество сообщений')
        plt.title('Топ 10 активных пользователей')
        plt.tight_layout()
        
        st.pyplot(fig)
    
    # Топ пользователей по реакциям
    if stats['top_users_by_reactions'] and sum(user['reactions'] for user in stats['top_users_by_reactions'].values()) > 0:
        st.subheader("Топ 10 пользователей по реакциям")
        
        top_10_users_reactions = list(stats['top_users_by_reactions'].items())[:10]
        
        user_names = [user[1]['name'] for user in top_10_users_reactions]
        user_reactions = [user[1]['reactions'] for user in top_10_users_reactions]
        
        if sum(user_reactions) > 0:  # Проверяем, есть ли вообще реакции
            fig, ax = plt.subplots(figsize=(10, 6))
            
            plt.barh(range(len(user_names)), user_reactions, color='purple', alpha=0.7)
            plt.yticks(range(len(user_names)), user_names)
            plt.xlabel('Количество реакций')
            plt.title('Топ 10 пользователей по полученным реакциям')
            plt.tight_layout()
            
            st.pyplot(fig)

def main():
    st.set_page_config(
        page_title="Telegram Group Analyzer",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    st.title("📊 Telegram Group Analyzer")
    st.markdown("Инструмент для анализа групп и каналов Telegram")
    
    # Сайдбар для ввода данных
    with st.sidebar:
        st.header("Настройки")
        
        # Вкладки для разных методов авторизации
        auth_tab = st.radio(
            "Выберите способ авторизации",
            ["По номеру телефона", "По строке сессии"]
        )
        
        error_container = st.empty()
        
        if auth_tab == "По номеру телефона":
            api_id = st.text_input("API ID", placeholder="12345", type="password")
            api_hash = st.text_input("API Hash", placeholder="0123456789abcdef0123456789abcdef", type="password")
            phone = st.text_input("Номер телефона", placeholder="+79123456789")
            
            st.markdown("""
            📝 **Как получить API ID и API Hash:**
            1. Перейдите на [my.telegram.org](https://my.telegram.org/auth)
            2. Войдите в свой аккаунт
            3. Нажмите "API development tools"
            4. Создайте новое приложение
            5. Скопируйте API ID и API Hash
            """)
            
            # Переменная сессии для хранения кода
            session_state = st.session_state
            if 'auth_code' not in session_state:
                session_state.auth_code = ""
            
            auth_code = st.text_input("Код авторизации (отправлен в Telegram)", 
                                     value=session_state.auth_code,
                                     placeholder="Введите код после запуска",
                                     key="auth_code_input")
            
            session_state.auth_code = auth_code
        
        else:  # По строке сессии
            session_string = st.text_area("Строка сессии", placeholder="Вставьте строку сессии...", height=100, type="password")
        
        group_link = st.text_input("Ссылка на группу или канал", placeholder="https://t.me/example или @example")
        days_count = st.slider("Период анализа (дней)", min_value=1, max_value=30, value=7)
        
        run_button = st.button("Запустить анализ", type="primary")
    
    # Основной контейнер для результатов
    result_container = st.container()
    
    # Обработка запроса
    if run_button:
        with result_container:
            progress_bar = st.progress(0, "Подготовка...")
            
            # Создание и авторизация клиента
            if auth_tab == "По номеру телефона":
                client = create_client_by_phone(api_id, api_hash, phone, error_container, session_state.auth_code)
            else:
                client = create_client_by_session(session_string, error_container)
            
            if client:
                progress_bar.progress(0.2, "Авторизация выполнена")
                
                # Запуск асинхронных функций
                async def run_analysis():
                    try:
                        await client.connect()
                        
                        # Получение данных о группе
                        progress_bar.progress(0.3, "Получение информации о группе...")
                        group_entity = await get_group_entity(client, group_link, error_container)
                        
                        if group_entity:
                            # Информация о группе
                            group_info = await get_group_info(client, group_entity, error_container)
                            
                            if group_info:
                                progress_bar.progress(0.4, "Группа найдена")
                                render_group_info(group_info)
                                
                                # Анализ сообщений
                                progress_bar.progress(0.5, "Анализ сообщений...")
                                st.subheader("Анализ сообщений")
                                st.write(f"Сбор статистики за последние {days_count} дней")
                                
                                messages_stats = await get_messages_stats(client, group_entity, days_count, error_container, progress_bar)
                                
                                if messages_stats:
                                    render_message_stats(messages_stats)
                                else:
                                    st.error("Не удалось получить статистику сообщений")
                            else:
                                st.error("Не удалось получить информацию о группе")
                        else:
                            st.error("Не удалось получить доступ к группе")
                    
                    finally:
                        await client.disconnect()
                
                # Запуск асинхронного анализа
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    loop.run_until_complete(run_analysis())
                finally:
                    loop.close()

if __name__ == "__main__":
    main()