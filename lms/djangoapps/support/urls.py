"""
URLs for support dashboard
"""
from django.conf.urls import patterns, url

from support import views

urlpatterns = patterns(
    '',
    # url(r'^$', permission_required('student.change_courseenrollment')(support.SupportDash.as_view()), name="support_dashboard"),
    # url(r'^refund/?$', permission_required('student.change_courseenrollment')(support.Refund.as_view()), name="support_refund"),
    url(r'^$', views.SupportIndex.as_view(), name="index")
)
