from django.contrib import admin
from .models import Article, Genre, Region, Source

admin.site.register(Region)
admin.site.register(Genre)
admin.site.register(Source)
admin.site.register(Article)