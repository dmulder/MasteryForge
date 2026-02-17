from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('content', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='KhanClass',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('slug', models.CharField(max_length=255, unique=True)),
                ('title', models.CharField(max_length=255)),
                ('subject', models.CharField(blank=True, max_length=200)),
                ('url', models.CharField(max_length=255)),
                ('raw_data', models.JSONField(blank=True, default=dict)),
                ('is_active', models.BooleanField(default=True)),
                ('fetched_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['subject', 'title'],
            },
        ),
    ]
