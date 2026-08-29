import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
import store.db as db
from ingest.pipeline import process_url
from utils.alert import send_slack_alert

logger = logging.getLogger(__name__)

def run_automated_pipeline():
    """
    Nightly job to check and update all indexed documents.
    """
    logger.info("Starting automated pipeline check...")
    documents = db.get_documents()
    
    if not documents:
        logger.info("No documents to check. Pipeline finished.")
        return

    updated_count = 0
    skipped_count = 0
    error_count = 0

    for doc in documents:
        url = doc['url']
        logger.info(f"Checking updates for: {url}")
        status, message, _ = process_url(url, force=False)
        
        if status == 'ok':
            updated_count += 1
            logger.info(f"Updated {url}: {message}")
        elif status == 'skipped':
            skipped_count += 1
            logger.info(f"Skipped {url}: {message}")
        else:
            error_count += 1
            logger.error(f"Error checking {url}: {message}")
            send_slack_alert(url, message)
            
    logger.info(f"Pipeline finished. Updated: {updated_count}, Skipped: {skipped_count}, Errors: {error_count}")

def start_scheduler():
    scheduler = BlockingScheduler()
    # Runs everyday at 03:00 AM
    scheduler.add_job(
        run_automated_pipeline,
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_pipeline",
        name="Nightly Automated RAG Pipeline",
        replace_existing=True
    )
    logger.info("Standalone scheduler started. Nightly pipeline scheduled for 03:00 AM.")
    scheduler.start()

if __name__ == "__main__":
    from logging.handlers import RotatingFileHandler
    log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler = RotatingFileHandler('app.log', maxBytes=10*1024*1024, backupCount=5)
    file_handler.setFormatter(log_formatter)
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(log_formatter)
    
    logging.basicConfig(level=logging.INFO, handlers=[file_handler, stream_handler])
    
    start_scheduler()
