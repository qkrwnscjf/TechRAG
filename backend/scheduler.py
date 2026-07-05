import logging
from apscheduler.schedulers.background import BackgroundScheduler
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
    scheduler = BackgroundScheduler()
    # Runs everyday at 03:00 AM
    scheduler.add_job(
        run_automated_pipeline,
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_pipeline",
        name="Nightly Automated RAG Pipeline",
        replace_existing=True
    )
    scheduler.start()
    logger.info("Background scheduler started. Nightly pipeline scheduled for 03:00 AM.")
