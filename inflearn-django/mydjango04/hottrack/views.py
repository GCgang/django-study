import pandas as pd
import datetime

from django.conf import settings
from django.db.models import QuerySet, Q
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import render, get_object_or_404
from io import BytesIO
from typing import Literal
from hottrack.models import Song
from hottrack.utils.cover import make_cover_image
from django.views.generic import DetailView, ListView, YearArchiveView, MonthArchiveView, DayArchiveView, TodayArchiveView, WeekArchiveView, ArchiveIndexView, DateDetailView

class IndexVeiw(ListView):
    model = Song
    paginate_by = 10
    template_name="hottrack/index.html"

    def get_queryset(self):
        qs = super().get_queryset()

        release_date = self.kwargs.get("release_date")
        if release_date:
            qs = qs.filter(release_date=release_date)

        query = self.request.GET.get("query", "").strip()
        if query:
            qs = qs.filter(
                Q(name__icontains=query)
                | Q(artist_name__icontains=query)
                | Q(album_name__icontains=query)
            )
        return qs
    
index = IndexVeiw.as_view()

# # 타입을 지정하면 이상한 타입추론도 줄이고 보다 빠르고 정확하게 자동완성을 제공받을 수 있다
# def index(request: HttpRequest, release_date: datetime.date = None) -> HttpResponse:  # view 함수의 반환 타입은 HttpResponse
#     query = request.GET.get("query", "").strip()

#     song_qs: QuerySet = Song.objects.all()
    
#     if release_date:
#         song_qs = song_qs.filter(release_date=release_date)

#     if query:
#         song_qs = song_qs.filter(
#             Q(name__icontains=query)
#             | Q(artist_name__icontains=query)
#             | Q(album_name__icontains=query)
#         )
#     return render(
#         request=request,
#         template_name="hottrack/index.html",
#         context={"song_list": song_qs, "query": query},
#     )

# pk 인자와 slug 인자를 그대로 사용하고, melon_uid 인자를 추가로 사용
class SongDetailView(DetailView):
    model=Song

    def get_object(self, queryset=None):
        if queryset is None:
            queryset = self.get_queryset()
        
        melon_uid = self.kwargs.get("melon_uid")
        if melon_uid:
            return get_object_or_404(queryset, melon_uid=melon_uid)
        
        return super().get_object(queryset)

song_detail = SongDetailView.as_view()


def cover_png(request, pk):
    # 최댓값 512, 기본값 256
    # http://127.0.0.1:8000/hottrack/501/cover.png?size=512 이렇게 요청되어 들어온 경우
    # size에 해당하는 값을 사용하고 제공되지 않은 경우 기본값 256을 사용함
    canvas_size = min(512, int(request.GET.get("size", 256)))

    # pk가 일치하는 객체를 찾으면 해당 객체 반환 아니면 404
    song = get_object_or_404(Song, pk=pk)

    cover_image = make_cover_image(
        song.cover_url, song.artist_name, canvas_size=canvas_size
    )

    # param fp : filename (str), pathlib.Path object or file object
    # image.save("image.png")
    response = HttpResponse(content_type="image/png")
    cover_image.save(response, format="png")

    return response


# 데이터를 CSV 또는 Excel 형식으로 내보내는 함수
def export(request: HttpRequest, format: Literal["csv", "xlsx"]) -> HttpResponse:
    song_qs = QuerySet = Song.objects.all()

    # .valuse() : 지정한 필드로 구성된 사전 리스트를 반환
    song_qs = song_qs.values()
    # 원하는 필드만 지정해서 뽑을 수도 있다.
    # song_qs = song_qs.values("rank", "name", "artist_name", "like_count")

    # 사전 리스트를 인자로 받아서, DataFrame을 생성할 수 있다
    df = pd.DataFrame(data=song_qs)

    # 메모리 파일 객체에 CSV 데이터 저장
    # CSV를 HttpResponse에 바로 저장할 떄 utf-8-sig 인코딩이 적용되지 않아서
    # BytesIO를 사용하여 인코딩을 적용한 후, HttpResponse에 저장한다
    export_file = BytesIO()

    if format == "csv":
        content_type = "text/csv"
        filename = "hottrack.csv"
        # df.to_csv("hottrack.csv", index=False)      # 지정 파일로 저장할 수도 있고, 파일 객체를 전달할 수도 있다.
        # (한글깨짐방지) 한글 엑셀에서는 CSV 텍스트 파일을 해석하는 기본 인코딩이 cp949이기에
        # utf-8-sig 인코딩을 적용하여 생성되는 CSV 파일에 UTF-8 BOM이 추가한다.
        df.to_csv(path_or_buf=export_file, index=False, encoding="utf-8-sig")  # noqa
    elif format == "xlsx":
        # .xls : application/vnd.ms-excel
        content_type = (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"  # xlsx
        )
        filename = "hottrack.xlsx"
        df.to_excel(excel_writer=export_file, index=False, engine="openpyxl")  # noqa
    else:
        return HttpResponseBadRequest(f"Invalid format : {format}")

    # 저장된 파일의 전체 내용을 HttpResponse에 전달
    response = HttpResponse(content=export_file.getvalue(), content_type=content_type)

    # Content-Disposition 헤더를 설정하여 브라우저가 해당 파일을 다운로드할 수 있도록 한다.
    response["Content-Disposition"] = "attachment; filename*=utf-8''{}".format(filename)

    return response


# 특정 해, 오늘 이하 범위에서 date_field 역순으로 쿼리셋을 생성한다
# 해당 범위 데이터가 많다면 페이징 처리가 필요할 수 있다
class SongYearArchiveView(YearArchiveView):
    model = Song
    date_field = "release_date" # 조회한 날짜 필드

    # 기준 년도 조회 순서
    # 1) 속성 "year" (고정)
    # 2) URL Captured Value "year" (가변)
    # 3) Query Parameter "year" (가변)
    year = None
    
    # YearArchiveView에만 있는 옵션
    # 디폴트 : False (데이터가 있는 날짜 목록만을 제공하고 템플릿에 object_list 빈 쿼리셋을 제공)
    make_object_list = True


# 특정 해/월, 오늘 이하 범위에서 date_field 역순으로 쿼리셋을 생성한다
# 해당 범위 데이터가 많다면 페이징 처리가 필요할 수 있다
class SongMonthArchiveView(MonthArchiveView):
    model = Song
    date_field = "release_date"
    # 날짜 포맷 : %m (숫자, ex: "01", "1" 등), %b (디폴트, 월 이름의 약어, ex: "Jan", "Feb" 등)
    month_format = "%m"

    # 기준 year/month 조회 순서
    # 1) 속성 (고정)
    # 2) URL Captured Value (가변)
    # 3) Query Parameter (가변)


# 특정 해/월/일, 오늘 이하 범위에서 date_field 역순으로 쿼리셋을 생성한다
# 해당 범위 데이터가 많다면 페이징 처리가 필요할 수 있다
class SongDayArchiveView(DayArchiveView):
    model = Song
    date_field = "release_date"
    month_format = "%m" # 숫자 포맷


    # 기준 year/month/day 조회 순서
    # 1) 속성 (고정)
    # 2) URL Captured Value (가변)
    # 3) Query Parameter (가변)

class SongTodayArchiveView(TodayArchiveView):
    model = Song
    date_field = "release_date"

    # Tip) DEBUG=True 에서만 get_dated_items 메서드를 재정의한다
    # 오늘 날짜 데이터를 조회할 때, 테스트를 위해 가짜 오늘 날짜를 지원한다
    if settings.DEBUG:
        def get_dated_items(self):
            """지정 날짜의 데이터를 조회"""
            fake_today = self.request.GET.get("fake-today", "")
            try:
                year, month, day = map(int, fake_today.split("-", 3))
                return self._get_dated_items(datetime.date(year, month, day))
            except ValueError:
                # fake_today 파라미터가 없거나 날짜 형식이 잘못된 경우
                return super().get_dated_items()


# 특정 해/주, 오늘 이하 범위에서 date_field 역순으로 쿼리셋을 생성한다
# 해당 범위 데이터가 많다면 페이징 처리가 필요할 수 있다
class SongWeekArchiveView(WeekArchiveView):
    model = Song
    date_field = "release_date"
    # date_list_period = "week"
    # 템플릿 필터 date의 "W" 포맷은 ISO 8601에 따라 한 주의 시작을 월요일로 간주한다.
    #  - 템플릿 단에서 한 주의 시작을 일요일로 할려면 커스텀 템플릿 태그 구현이 필요하다.
    week_format = "%W"  # "%U" (디폴트, 한 주의 시작을 일요일), %W (한 주의 시작을 월요일)

    # 기준 year/week 조회 순서
    # 1) 속성 (고정)
    # 2) URL Captured Value (가변)
    # 3) Query Parameter (가변)


# date_field 역순으로 쿼리셋을 생성한다
# date_list_period 에 지정한 단위로 date_list를 뽑는다
class SongArchiveIndexView(ArchiveIndexView):
    model = Song
    date_field = "release_date" # 기준 날짜 필드
    paginate_by = 10 # 전체 목록을 조회하기에 페이징 처리가 필수

    # date_list_period = "year"
    # 단위 : year(디폴트), month, day, week
    def get_date_list_period(self):
        # URL Captured Value에 date_list_period가 없으면, date_list_period 속성을 활용한다
        return self.kwargs.get("date_list_period", self.date_list_period)
    
    def get_context_data(self, **kwargs):
        context_data = super().get_context_data(**kwargs)
        context_data["date_list_period"] = self.get_date_list_period()
        return context_data
    

# 디폴트 템플릿 : hottrack/song_detail.html
class SongDateDetailView(DateDetailView):
    model = Song
    date_field = "release_date"
    month_format = "%m"