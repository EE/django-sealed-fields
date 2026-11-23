from django import template

from ..sealed import reveal


register = template.Library()

# {{ invitation.code|reveal }}: the one way a template shows a Sealed.
register.filter('reveal', reveal)
