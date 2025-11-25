import os
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import pdfplumber
from gtts import gTTS
import asyncio
import tempfile
import shutil


#Load environment variables 
load_dotenv()

# Enable logging
logging.basicConfig(
    format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level = logging.INFO
)

logger = logging.getLogger(__name__)

# Get the bot token from environment variables
TOKEN = os.getenv('BOT_TOKEN')
if not TOKEN:
    raise ValueError("No BOT_TOKEN found in environment variables.")


def pdf_to_audio(pdf_path, output_audio_path='output.mp3', language='en'):
    """
    Converts a PDF file to an MP3 audio file.
    
    Args:
        pdf_path (str): Path to the input PDF file.
        output_audio_path (str): Path for the output MP3 file.
        language (str): Language code for TTS (e.g., 'en' for English, 'es' for Spanish).
    """
    full_text = ""
    
    # Extract text from PDF page by page
    logger.info(f"Extracting text from PDF: {pdf_path}")
    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages):
            print(f"Processing page {page_num + 1}...")
            page_text = page.extract_text()
            if page_text:
                full_text += page_text + "\n" # Add a newline between pages
    
    if not full_text.strip():
        raise ValueError("No text could be extracted from the PDF. It might be a scanned image-based PDF.")
    
    # Clean the text: remove excessive newlines, handle special characters
    # This is a simple clean-up; you might need more robust processing.
    cleaned_text = ' '.join(full_text.split())
    
    # Check text length (gTTS has a ~5000 character limit per request)
    # We need to split the text into chunks.
    logger.info("Converting text to speech...")
    text_chunks = [cleaned_text[i:i+4000] for i in range(0, len(cleaned_text), 4000)]
    
    # For multiple chunks, we need to create multiple files and then combine them.
    # For simplicity, let's handle the first chunk for now and warn the user.
    if len(text_chunks) > 1:
        logger.warning(f"PDF is large ({len(cleaned_text)} chars). Processing first 4000 characters only. Advanced version needed for full book.")
        text_to_convert = text_chunks[0]
    else:
        text_to_convert = cleaned_text
    
    # Create the TTS object and save to file
    tts = gTTS(text=text_to_convert, lang=language, slow=False)
    tts.save(output_audio_path)
    logger.info(f"Audio saved to: {output_audio_path}")
    
    
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Sends a welcome message when the command /start is issued."""
    user = update.effective_user
    welcome_text = f"""
    Hi {user.mention_html()}!
    
    I am your Personal PDF Audiobook Reader Bot.
    
    **How to use me:**
    1.  Simply send me a PDF file.
    2.  I will extract the text and convert it to an audio file.
    3.  I will then send the audio file back to you.
    
    Please note: I work best with text-based PDFs, not scanned images. For large books, I might only process the first few pages in this version.
    """
    await update.message.reply_html(welcome_text)
    
    
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles incoming PDF documents."""
    user = update.effective_user
    chat_id = update.effective_chat.id

    # Check if the document is a PDF
    document = update.message.document
    if document.mime_type != 'application/pdf':
        await update.message.reply_text("Please send a PDF file.")
        return

    # Send a "processing" message
    status_message = await update.message.reply_text("📥 PDF received. Starting processing... This may take a while.")

    # Create a temporary directory to work in
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            # 1. Download the PDF file
            pdf_file = await context.bot.get_file(document.file_id)
            pdf_path = os.path.join(tmp_dir, document.file_name)
            await pdf_file.download_to_drive(pdf_path)
            await status_message.edit_text("✅ PDF downloaded. Extracting text...")

            # 2. Define the output audio path
            audio_filename = os.path.splitext(document.file_name)[0] + ".mp3"
            audio_path = os.path.join(tmp_dir, audio_filename)

            # 3. Convert PDF to Audio (this is a blocking call, we run it in a thread)
            loop = asyncio.get_running_loop()
            await status_message.edit_text("🔊 Converting text to speech...")
            await loop.run_in_executor(None, pdf_to_audio, pdf_path, audio_path)

            # 4. Send the audio file back to the user
            await status_message.edit_text("📤 Sending audio file...")
            with open(audio_path, 'rb') as audio_file:
                await context.bot.send_audio(chat_id=chat_id, audio=audio_file, title=audio_filename)

            # 5. Clean up and send final message
            await status_message.delete()
            await update.message.reply_text("🎧 Enjoy your audiobook! Send another PDF if you like.")

        except ValueError as e:
            # Handle errors from our pdf_to_audio function
            await status_message.edit_text(f"❌ Error: {str(e)}")
            logger.error(f"ValueError in handle_document: {e}")
        except Exception as e:
            # Handle any other unexpected errors
            await status_message.edit_text("❌ An unexpected error occurred during processing. Please try again with a different PDF.")
            logger.error(f"Unexpected error in handle_document: {e}", exc_info=True)


def main() -> None:
    """Start the bot."""
    # Create the Application with longer timeouts for slow networks
    application = (
        Application.builder()
        .token(TOKEN)
        .connect_timeout(60.0)
        .read_timeout(60.0)
        .write_timeout(120.0)  # Longer timeout for uploading audio files
        .pool_timeout(60.0)
        .build()
    )

    # Register command handlers
    application.add_handler(CommandHandler("start", start))
    
    # Register document handler for PDF files
    application.add_handler(MessageHandler(filters.Document.PDF, handle_document))

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()