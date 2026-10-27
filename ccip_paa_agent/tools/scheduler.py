
from apscheduler.schedulers.blocking import BlockingScheduler

from tools.news_monitor import (
    setup_database,
    run_rss_job,
    run_tinyfish_job,
)

def main():
    setup_database()

    scheduler = BlockingScheduler()

    # RSS collection every 15 minutes
    scheduler.add_job(
        run_rss_job,
        trigger="interval",
        minutes=15,
        id="rss_news_job",
        max_instances=1,
        coalesce=True,
    )

    # TinyFish freshness check every 60 minutes
    scheduler.add_job(
        run_tinyfish_job,
        trigger="interval",
        minutes=60,
        id="tinyfish_news_job",
        max_instances=1,
        coalesce=True,
    )

    print("CryptoGuardian scheduler started.")
    print("RSS: every 15 minutes")
    print("TinyFish: every 60 minutes")
    print("News retention: 3 hours")

    # Run both jobs once at startup
    run_rss_job()
    run_tinyfish_job()

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("Scheduler stopped.")

if __name__ == "__main__":
    main()
