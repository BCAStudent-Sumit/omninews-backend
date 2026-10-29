from django.db import migrations


def seed_plans(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')

    # Seed Pro Plan
    Plan.objects.get_or_create(
        slug='pro',
        defaults={
            'name': 'OmniNews Pro',
            'price_inr': 199.00,
            'interval': 'monthly',
            'features': [
                'Ad-free reading & clean news experience',
                'Unlimited Gemini AI audio deep-dives',
                'Live Telecast 2D broadcast access',
                'Background audio player & smart playlists',
                'Priority real-time AI breaking summaries'
            ],
            'store_product_id': 'omninews_pro_monthly',
            'active': True,
        }
    )

    # Seed Exclusive Plan
    Plan.objects.get_or_create(
        slug='exclusive',
        defaults={
            'name': 'OmniNews Exclusive',
            'price_inr': 499.00,
            'interval': 'monthly',
            'features': [
                'All features included in Pro tier',
                '360° VR Immersive Live Telecast broadcasts',
                'Multi-angle interactive broadcast view',
                'Direct studio Q&A & live polling',
                'Early access to next-gen voice assistants'
            ],
            'store_product_id': 'omninews_exclusive_monthly',
            'active': True,
        }
    )


def unseed_plans(apps, schema_editor):
    Plan = apps.get_model('subscriptions', 'Plan')
    Plan.objects.filter(slug__in=['pro', 'exclusive']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('subscriptions', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_plans, reverse_code=unseed_plans),
    ]
