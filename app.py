import streamlit as st
import asyncio
import pandas as pd
import os
import re
import time
from telethon import TelegramClient, sync
from telethon.tl.functions.messages import GetHistoryRequest
from io import BytesIO

# Set page configuration
st.set_page_config(
    page_title="Telegram Group Posts Extractor",
    page_icon="📱",
    layout="wide"
)

# Title and description
st.title("Telegram Group Posts Extractor")
st.markdown("""
This app allows you to extract posts from specified Telegram groups based on keywords or expressions.
Enter your API credentials, specify the groups and keyword to search for, and download the results.
""")

# TelegramExtractor class definition
class TelegramExtractor:
    def __init__(self, api_id, api_hash):
        self.api_id = api_id
        self.api_hash = api_hash
        self.client = None
        
    async def initialize(self):
        self.client = TelegramClient('session_name', self.api_id, self.api_hash)
        await self.client.start()
        
    async def close(self):
        if self.client:
            await self.client.disconnect()
            
    async def extract_messages(self, group_links, keyword, limit=1000):
        """
        Extract messages from specified Telegram groups that contain the keyword
        
        Args:
            group_links (list): List of Telegram group links
            keyword (str): Keyword to search for
            limit (int): Maximum number of messages to fetch per group
            
        Returns:
            pd.DataFrame: DataFrame containing the extracted messages
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
                entity = await self.client.get_entity(group_name)
                
                # Get messages
                messages = await self.client(GetHistoryRequest(
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
                        if message.from_id:
                            sender = await self.client.get_entity(message.from_id)
                            sender_name = f"{sender.first_name} {sender.last_name if sender.last_name else ''}"
                            sender_username = sender.username if hasattr(sender, 'username') else None
                        else:
                            sender_name = "Unknown"
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
                
            except Exception as e:
                print(f"Error extracting messages from {group_link}: {e}")
                
        # Create DataFrame
        df = pd.DataFrame(results)
        
        # Sort by date (newest first)
        if not df.empty:
            df = df.sort_values(by='date', ascending=False)
            
        return df
        
    def get_dataframe_excel(self, df):
        """Convert DataFrame to Excel file bytes for download"""
        output = BytesIO()
        with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name='Telegram Posts', index=False)
        output.seek(0)
        return output.getvalue()
    
    def get_dataframe_csv(self, df):
        """Convert DataFrame to CSV file bytes for download"""
        output = BytesIO()
        df.to_csv(output, index=False)
        output.seek(0)
        return output.getvalue()

# Create layout with sidebar and main content
# Sidebar for user inputs
with st.sidebar:
    st.header("Telegram API Credentials")
    st.markdown("""
    To use this app, you need Telegram API credentials. 
    Get them at [my.telegram.org](https://my.telegram.org/auth?to=apps).
    """)
    
    api_id = st.text_input("API ID", type="password")
    api_hash = st.text_input("API Hash", type="password")
    
    st.header("Search Parameters")
    
    # Group links - one per line
    group_links = st.text_area(
        "Telegram Group Links (one per line)",
        placeholder="groupname1\ngroupname2\nhttps://t.me/groupname3",
        help="Enter Telegram group links or group usernames, one per line"
    )
    
    # Keyword or expression
    keyword = st.text_input(
        "Keyword or Expression",
        placeholder="Enter search term",
        help="Posts containing this keyword or expression will be extracted"
    )
    
    # Message limit
    message_limit = st.number_input(
        "Maximum messages to fetch per group",
        min_value=100,
        max_value=5000,
        value=1000,
        step=100,
        help="Higher numbers may take longer to process"
    )
    
    # Extract button
    extract_button = st.button("Extract Posts", type="primary")

# Right side - Instructions and information
with st.expander("How to use this app", expanded=True):
    st.markdown("""
    ### Instructions
    
    1. **Get API Credentials**:
       - Go to [my.telegram.org](https://my.telegram.org/auth)
       - Log in with your phone number
       - Click on "API Development Tools"
       - Create a new application
       - Copy the API ID and API Hash
    
    2. **Enter Group Information**:
       - Enter group usernames or full links (e.g., `groupname` or `https://t.me/groupname`)
       - One group per line
    
    3. **Specify Search Criteria**:
       - Enter the keyword or phrase you want to find
       - Adjust the maximum number of messages to search through
    
    4. **Run and Download**:
       - Click "Extract Posts" to start the search
       - Download results as Excel or CSV
    
    ### Notes
    
    - First-time usage requires phone verification through Telegram
    - Extraction may take some time for large groups
    - Always respect privacy and Telegram's terms of service
    """)

# Main content area
if extract_button:
    if not api_id or not api_hash:
        st.error("Please enter your Telegram API credentials")
    elif not group_links:
        st.error("Please enter at least one Telegram group")
    elif not keyword:
        st.error("Please enter a keyword or expression to search for")
    else:
        # Process the group links (split by newline and remove empty lines)
        group_list = [line.strip() for line in group_links.split('\n') if line.strip()]
        
        with st.spinner(f"Extracting posts containing '{keyword}' from {len(group_list)} groups..."):
            try:
                # Initialize extractor
                extractor = TelegramExtractor(api_id=api_id, api_hash=api_hash)
                
                # Run the extraction asynchronously
                async def run_extraction():
                    await extractor.initialize()
                    df = await extractor.extract_messages(group_list, keyword, limit=message_limit)
                    await extractor.close()
                    return df
                
                # Run the async function
                df = asyncio.run(run_extraction())
                
                # Display results
                if df.empty:
                    st.warning(f"No posts found containing '{keyword}' in the specified groups.")
                else:
                    st.success(f"Found {len(df)} posts containing '{keyword}'!")
                    
                    # Show dataframe
                    st.dataframe(
                        df[['group', 'date', 'sender_name', 'message', 'message_link']],
                        hide_index=True,
                        use_container_width=True
                    )
                    
                    # Download buttons
                    col1, col2 = st.columns(2)
                    with col1:
                        excel_data = extractor.get_dataframe_excel(df)
                        st.download_button(
                            label="Download as Excel",
                            data=excel_data,
                            file_name=f"telegram_posts_{keyword}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    
                    with col2:
                        csv_data = extractor.get_dataframe_csv(df)
                        st.download_button(
                            label="Download as CSV",
                            data=csv_data,
                            file_name=f"telegram_posts_{keyword}_{time.strftime('%Y%m%d_%H%M%S')}.csv",
                            mime="text/csv"
                        )
                    
            except Exception as e:
                st.error(f"An error occurred: {str(e)}")

# Add footer
st.markdown("---")
st.markdown("📱 Telegram Group Posts Extractor | Made with Streamlit and Telethon")
