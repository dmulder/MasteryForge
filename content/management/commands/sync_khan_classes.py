from django.core.management.base import BaseCommand

from content.khan import KhanScrapeError, sync_khan_classes


class Command(BaseCommand):
    help = 'Scrape Khan Academy class list and update cache.'

    def handle(self, *args, **options):
        try:
            result = sync_khan_classes()
        except KhanScrapeError as exc:
            self.stdout.write(self.style.ERROR(f'Failed to sync Khan classes: {exc}'))
            return

        self.stdout.write(self.style.SUCCESS(
            f'Synced {len(result.classes)} Khan classes.'
        ))
