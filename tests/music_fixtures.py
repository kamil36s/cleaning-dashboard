def chart_html(entries, *, marker="", canonical="https://rateyourmusic.com/charts/top/album/all-time/g:ambient-americana/"):
    items = []
    for index, entry in enumerate(entries, 1):
        release_id = entry.get("id", 1000 + index)
        artist = entry["artist"]
        title = entry["title"]
        slug = entry.get("slug", title.lower().replace(" ", "-"))
        year = entry.get("year", 2021)
        items.append(f"""
        <div class="page_charts_section_charts_item object_release" id="page_charts_section_charts_item_{release_id}">
          <div class="page_charts_section_charts_item_number"><div></div></div>
          <picture class="page_charts_section_charts_item_image"><source srcset="//img.test/{release_id}.jpg 1x"><img src="./fixture_files/{release_id}.jpg"></picture>
          <a class="page_charts_section_charts_item_link release" href="https://rateyourmusic.com/release/album/{artist.lower().replace(' ', '-')}/{slug}/"><span class="ui_name_locale_original">{title}</span></a>
          <div class="page_charts_section_charts_item_credited_text"><a class="artist">{artist}</a></div>
          <div class="page_charts_section_charts_item_date"><span>{year}</span><span class="page_charts_section_charts_item_release_type">Album</span></div>
          <div class="page_charts_section_charts_item_genres_primary"><a href="https://rateyourmusic.com/genre/ambient-americana/">Ambient Americana</a></div>
          <div class="page_charts_section_charts_item_genres_secondary"><a href="https://rateyourmusic.com/genre/drone/">Drone</a></div>
          <div class="page_charts_section_charts_item_genre_descriptors"><span class="comma_separated">calm</span></div>
          <span class="page_charts_section_charts_item_details_average_num">3.80</span>
          <span class="page_charts_section_charts_item_details_ratings"><span class="abbr">2k</span></span>
          <span class="page_charts_section_charts_item_details_reviews"><span class="abbr">12</span></span>
        </div>""")
    return f"<html><head><title>Best Ambient Americana albums - Rate Your Music</title><link rel='canonical' href='{canonical}'></head><body id='page_charts'>{marker}{''.join(items)}</body></html>"


def release_html(*, release_id=14012000, artist="Old Saw", title="Country Tropics", slug="country-tropics"):
    return f"""<html><head><title>{title} by {artist} - Rate Your Music</title><meta property="og:url" content="https://rateyourmusic.com/release/album/{artist.lower().replace(' ', '-')}/{slug}/"></head>
    <body id="page_release" class="release_page">
      <div itemprop="aggregateRating"><meta itemprop="ratingValue" content="3.78"><meta itemprop="ratingCount" content="4145"><meta itemprop="reviewCount" content="31"></div>
      <div class="section_main_info"><meta itemprop="name" content="{title}"><div class="album_title">{title}<input class="album_shortcut" value="[Album{release_id}]"></div>
      <table class="album_info"><tr><th class="info_hdr">Artist</th><td><span itemprop="byArtist"><a class="artist">{artist}</a></span></td></tr><tr><th class="info_hdr">Type</th><td>Album</td></tr><tr><th class="info_hdr">Released</th><td>19 November 2021</td></tr><tr><th class="info_hdr">Recorded</th><td>February 2021</td></tr>
      <tr><th class="info_hdr">Genres</th><td><span class="release_pri_genres"><a href="https://rateyourmusic.com/genre/ambient-americana/">Ambient Americana</a></span><span class="release_sec_genres"><a href="https://rateyourmusic.com/genre/american-primitivism/">American Primitivism</a><a href="https://rateyourmusic.com/genre/free-folk/">Free Folk</a><a href="https://rateyourmusic.com/genre/drone/">Drone</a></span></td></tr>
      <tr class="release_descriptors"><td><meta content="calm"><meta content="warm"></td></tr></table></div>
      <img class="cover" alt="Cover art for {title}" src="./fixture_files/cover.jpg">
      <ul id="tracks_mobile" class="tracks tracklisting"><li class="track"><span class="tracklist_num">A1</span><span class="tracklist_title"><a class="song">First Song</a><span class="tracklist_duration" data-inseconds="125">2:05</span></span></li></ul>
      <ul id="credits_credits_mobile" class="credits"><li><a class="artist">Person One</a><span class="role_name">guitar</span></li></ul>
    </body></html>"""


GENRE_HTML = """<html><head><title>Music Genres - Rate Your Music</title></head><body id="page_genre_index"><section id="page_genre_index_section_hierarchy"><ul class="page_genre_index_hierarchy"><li class="page_genre_index_hierarchy_item"><div class="page_genre_index_hierarchy_item_main"><div class="page_genre_index_hierarchy_item_main_inner"><h2><a href="https://rateyourmusic.com/genre/ambient/">Ambient</a></h2><p class="page_genre_index_hierarchy_item_description">Texture and atmosphere.</p></div></div><div class="page_genre_index_hierarchy_item_expanded"><ul class="hierarchy_list"><li class="hierarchy_list_item"><div class="hierarchy_list_item_details"><a href="https://rateyourmusic.com/genre/ambient-americana/">Ambient Americana</a><p>Pastoral Americana instrumentation.</p></div><ul class="hierarchy_list"><li class="hierarchy_list_item"><div class="hierarchy_list_item_details"><a href="https://rateyourmusic.com/genre/example-child/">Example Child</a><p>Nested child.</p></div></li></ul></li></ul></div></li></ul></section></body></html>"""

