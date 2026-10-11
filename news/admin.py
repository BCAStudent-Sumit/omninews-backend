from django.contrib import admin
from .models import Article, Genre, Region, Source ,ClarificationClaim, Evidence, ClaimVote, Bookmark

admin.site.register(Region)
admin.site.register(Genre)
admin.site.register(Source)
admin.site.register(Article)
admin.site.register(ClarificationClaim)
admin.site.register(Evidence)
admin.site.register(ClaimVote)
admin.site.register(Bookmark)