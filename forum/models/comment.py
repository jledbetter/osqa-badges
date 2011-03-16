from base import *
from django.utils.translation import ugettext as _
from django.utils.safestring import mark_safe
import re

class Comment(Node):
    friendly_name = _("comment")

    class Meta(Node.Meta):
        ordering = ('-added_at',)
        proxy = True

    def _update_parent_comment_count(self, diff):
        parent = self.parent
        parent.comment_count = parent.comment_count + diff
        parent.save()

    @property
    def comment(self):
        prev_body = self.body
        self.body = prev_body[:3] + self.prefix() + prev_body[3:]
        if settings.FORM_ALLOW_MARKDOWN_IN_COMMENTS:
            result = self.as_markdown('limitedsyntax')
        else:
            result = self.body
        self.body = prev_body
        return result

    @property
    def headline(self):
        return self.absolute_parent.headline

    @property
    def content_object(self):
        return self.parent.leaf

    def save(self, *args, **kwargs):
        super(Comment,self).save(*args, **kwargs)

        if not self.id:
            self.parent.reset_comment_count_cache()

    def mark_deleted(self, user):
        if super(Comment, self).mark_deleted(user):
            self.parent.reset_comment_count_cache()

    def unmark_deleted(self):
        if super(Comment, self).unmark_deleted():
            self.parent.reset_comment_count_cache()

    def is_reply_to(self, user):
        inreply = re.search('@\w+', self.body)
        if inreply is not None:
            return user.username.startswith(inreply.group(0))

        return False

    def get_absolute_url(self):
        return self.abs_parent.get_absolute_url() + "#%d" % self.id

    def __unicode__(self):
        return self.body

    def prefix(self):
        try:
            vote_comment = self.vote_comment.get()
            if vote_comment.comment_type == VoteComment.COMMENT:
                return ''
            else:
                return vote_comment.get_comment_type_display() + ': '
        except VoteComment.DoesNotExist:
            return ''

class VoteComment(models.Model):

    COMMENT, VOTE_UP, CANCEL_VOTE_UP, VOTE_DOWN, CANCEL_VOTE_DOWN = range(1, 6)

    comment_type_choices = ((COMMENT, _('Comment')),
        (VOTE_UP, _('Vote Up')),
        (CANCEL_VOTE_UP, _('Cancel Vote Up')),
        (VOTE_DOWN, _('Vote Down')),
        (CANCEL_VOTE_DOWN, _('Cancel Vote Down')))

    comment_type = models.PositiveSmallIntegerField(choices=comment_type_choices, default=COMMENT)

    comment = models.ForeignKey('Comment', related_name='vote_comment')

    class Meta:
        app_label = 'forum'


class AwardComment(Node):
    friendly_name = _("award comment")

    class Meta(Node.Meta):
        ordering = ('-added_at',)
        proxy = True

