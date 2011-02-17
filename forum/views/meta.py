import os
from itertools import groupby
from django.shortcuts import render_to_response, get_object_or_404
from django.core.urlresolvers import reverse
from django.template import RequestContext, loader
from django.http import HttpResponseRedirect, HttpResponse, Http404
from django.views.static import serve
from forum import settings
from forum.modules import decorate
from forum.views.decorators import login_required
from forum.forms import FeedbackForm
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext as _
from django.db.models import Count
from forum.forms import get_next_url, AwardBadgeForm
from forum.models import Badge, Award, User, Page, CustomBadge, Question, Answer, AwardComment
from forum.badges.base import BadgesMeta, award_badge
from forum import settings
from forum.utils.mail import send_template_email
from django.utils.safestring import mark_safe
from forum.templatetags.extra_filters import or_preview
from forum.views.readers import QuestionListPaginatorContext
from forum.utils import pagination
import decorators
import re

def favicon(request):
    return HttpResponseRedirect(str(settings.APP_FAVICON))

def custom_css(request):
    return HttpResponse(or_preview(settings.CUSTOM_CSS, request), mimetype="text/css")

def static(request, title, content):
    return render_to_response('static.html', {'content' : content, 'title': title},
                              context_instance=RequestContext(request))

def media(request, skin, path):
    response = serve(request, "%s/media/%s" % (skin, path),
                 document_root=os.path.join(os.path.dirname(os.path.dirname(__file__)), 'skins').replace('\\', '/'))
    content_type = response['Content-Type']
    if ('charset=' not in content_type):
        if (content_type.startswith('text') or content_type=='application/x-javascript'):
            content_type += '; charset=utf-8'
            response['Content-Type'] = content_type
    return response


def markdown_help(request):
    return render_to_response('markdown_help.html', context_instance=RequestContext(request))


def opensearch(request):
    return render_to_response('opensearch.html', {'settings' : settings}, context_instance=RequestContext(request))


def feedback(request):
    if request.method == "POST":
        form = FeedbackForm(request.user, data=request.POST)
        if form.is_valid():
            context = {
                 'user': request.user,
                 'email': request.user.is_authenticated() and request.user.email or form.cleaned_data.get('email', None),
                 'message': form.cleaned_data['message'],
                 'name': request.user.is_authenticated() and request.user.username or form.cleaned_data.get('name', None),
                 'ip': request.META['REMOTE_ADDR'],
            }

            recipients = User.objects.filter(is_superuser=True)
            send_template_email(recipients, "notifications/feedback.html", context)

            msg = _('Thanks for the feedback!')
            request.user.message_set.create(message=msg)
            return HttpResponseRedirect(get_next_url(request))
    else:
        form = FeedbackForm(request.user, initial={'next':get_next_url(request)})

    return render_to_response('feedback.html', {'form': form}, context_instance=RequestContext(request))

feedback.CANCEL_MESSAGE=_('We look forward to hearing your feedback! Please, give it next time :)')

def privacy(request):
    return render_to_response('privacy.html', context_instance=RequestContext(request))

@decorate.withfn(login_required)
def logout(request):
    return render_to_response('logout.html', {
    'next' : get_next_url(request),
    }, context_instance=RequestContext(request))

class BadgesPaginatorContext(pagination.PaginatorContext):
    def __init__(self):
        super (BadgesPaginatorContext, self).__init__('BADGE_LIST', sort_methods=(
            (_('type'), pagination.SimpleSort(_('by type'), '-type', _("sorted by type of badge"))),
            (_('name'), pagination.SimpleSort(_('by name'), 'cls', _("sorted alphabetically by name"))),
            (_('award'), pagination.SimpleSort(_('by awards'), '-awarded_count', _("sorted by number of awards"))),
        ), default_sort=_('type'), pagesizes=(5, 10, 20), default_pagesize=20, prefix=_('badge'))

@decorators.render('badges.html', 'badges', _('badges'), weight=300)
def badges(request):
    CustomBadge.load_custom_badges()
    badges = Badge.objects.all()

    if request.user.is_authenticated():
        my_badges = Award.objects.filter(user=request.user).values('badge_id').distinct()
    else:
        my_badges = []

    return pagination.paginated(request, ('badges', BadgesPaginatorContext()), {
        'badges' : badges,
        'mybadges' : my_badges,
    })

class BadgesAnswersPaginatorContext(pagination.PaginatorContext):
    def __init__(self):
        super (BadgesAnswersPaginatorContext, self).__init__('BADGE_ANSWER_LIST', sort_methods=(
            (_('oldest'), pagination.SimpleSort(_('oldest answers'), 'added_at', _("oldest answers will be shown first"))),
            (_('newest'), pagination.SimpleSort(_('newest answers'), '-added_at', _("newest answers will be shown first"))),
            (_('votes'), pagination.SimpleSort(_('popular answers'), '-score', _("most voted answers will be shown first"))),
            (_('author'), pagination.SimpleSort(_('by author'), 'author', _("sorted alphabetically by author"))),
        ), default_sort=_('votes'), pagesizes=(5, 10, 20), default_pagesize=10, prefix=_('answers'))

class BadgesAwardCommentsPaginatorContext(pagination.PaginatorContext):
    def __init__(self):
        super (BadgesAwardCommentsPaginatorContext, self).__init__('BADGE_ANSWER_LIST', sort_methods=(
            (_('oldest'), pagination.SimpleSort(_('oldest answers'), 'awarded_at', _("oldest answers will be shown first"))),
            (_('newest'), pagination.SimpleSort(_('newest answers'), '-awarded_at', _("newest answers will be shown first"))),
            (_('receiver'), pagination.SimpleSort(_('by receiver'), 'user', _("sorted alphabetically by the peer who received the badge"))),
            (_('giver'), pagination.SimpleSort(_('by giver'), 'node__author', _("sorted alphabetically by the peer who gave the badge"))),
        ), default_sort=_('newest'), pagesizes=(5, 10, 20), default_pagesize=10, prefix=_('award_comments'))

def badge(request, id, slug):
    badge = Badge.objects.get(id=id)
    award_queryset = Award.objects.filter(badge=badge)
    awards = list(award_queryset.order_by('user', 'awarded_at'))
    award_count = len(awards)

    awards = sorted([dict(count=len(list(g)), user=k) for k, g in groupby(awards, lambda a: a.user)],
                    lambda c1, c2: c2['count'] - c1['count'])

    kwargs = {
        'award_count': award_count,
        'awards' : awards,
        'badge' : badge,
        'requires_submitted_work': False,
        'peer_given': False,
    }

    try:
        custom_badge = badge.custombadge_set.get()
        if custom_badge.is_peer_given:
            if request.POST:
                kwargs['award_form'] = AwardBadgeForm(request.POST, user=request.user)
            else:
                kwargs['award_form'] = AwardBadgeForm(user=request.user)
            if request.method == "POST" and kwargs['award_form'].is_valid():
                award_comment = AwardComment(author=request.user, body=kwargs['award_form'].cleaned_data['text'])
                award_comment.save()
                class DummyAction:
                    node = award_comment
                award_badge(badge, kwargs['award_form'].cleaned_data['user'], DummyAction(), False)
                return HttpResponseRedirect(badge.get_absolute_url() + "#%s" % award_comment.id)
            kwargs['peer_given'] = True
            kwargs['award_comments'] = award_queryset
            kwargs = pagination.paginated(request,
                ('award_comments', BadgesAwardCommentsPaginatorContext()), kwargs)
        elif custom_badge.min_required_votes > 0:
            kwargs['requires_submitted_work'] = True
            kwargs['questions'] = Question.objects.filter_state(deleted=False).filter_tag(
                custom_badge.tag_name).order_by('-added_at')
            kwargs['answers'] = Answer.objects.filter_state(deleted=False).filter(
                parent__id__in=[q.id for q in kwargs['questions']]).order_by('-score')
            kwargs = pagination.paginated(request, (
                ('questions', QuestionListPaginatorContext('USER_QUESTION_LIST', _('questions'), 3)),
                ('answers', BadgesAnswersPaginatorContext())), kwargs)
    except CustomBadge.DoesNotExist:
        pass

    return render_to_response('badge.html', kwargs,
        context_instance=RequestContext(request))

def page(request, path):
    if path in settings.STATIC_PAGE_REGISTRY:
        try:
            page = Page.objects.get(id=settings.STATIC_PAGE_REGISTRY[path])

            if (not page.published) and (not request.user.is_superuser):
                raise Http404
        except:
            raise Http404
    else:
        raise Http404

    template = page.extra.get('template', 'default')
    sidebar = page.extra.get('sidebar', '')

    if template == 'default':
        base = 'base_content.html'
    elif template == 'sidebar':
        base = 'base.html'

        sidebar_render = page.extra.get('render', 'markdown')

        if sidebar_render == 'markdown':
            sidebar = page._as_markdown(sidebar)
        elif sidebar_render == 'html':
            sidebar = mark_safe(sidebar)

    else:
        return HttpResponse(page.body, mimetype=page.extra.get('mimetype', 'text/html'))

    render = page.extra.get('render', 'markdown')

    if render == 'markdown':
        body = page.as_markdown()
    elif render == 'html':
        body = mark_safe(page.body)
    else:
        body = page.body

    return render_to_response('page.html', {
    'page' : page,
    'body' : body,
    'sidebar': sidebar,
    'base': base,
    }, context_instance=RequestContext(request))


