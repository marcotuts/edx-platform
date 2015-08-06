from rest_framework import serializers
from django.contrib.auth.models import User
from django.contrib.sites.models import get_current_site
from django.conf import settings
from django.core.urlresolvers import reverse
from openedx.core.djangoapps.user_api.accounts import NAME_MIN_LENGTH
from openedx.core.djangoapps.user_api.serializers import ReadOnlyFieldsSerializerMixin

from student.models import UserProfile, LanguageProficiency
from ..models import UserPreference
from .image_helpers import get_profile_image_urls_for_user
from . import (
    ACCOUNT_VISIBILITY_PREF_KEY, ALL_USERS_VISIBILITY, PRIVATE_VISIBILITY,
)


PROFILE_IMAGE_KEY_PREFIX = 'image_url'


class LanguageProficiencySerializer(serializers.ModelSerializer):
    """
    Class that serializes the LanguageProficiency model for account
    information.
    """
    class Meta(object):  # pylint: disable=missing-docstring
        model = LanguageProficiency
        fields = ("code",)

    def get_identity(self, data):
        """
        This is used in bulk updates to determine the identity of an object.
        The default is to use the id of an object, but we want to override that
        and consider the language code to be the canonical identity of a
        LanguageProficiency model.
        """
        try:
            return data.get('code', None)
        except AttributeError:
            return None

class AccountFullUserProfileReadOnlySerializer(serializers.Serializer):
    """
    Class that serializes the portion of User model needed for account information.
    """
    def __init__(self, *args, **kwargs):
        # Don't pass the 'configuration' arg up to the superclass
        self.configuration = kwargs.pop('configuration', None)
        if not self.configuration:
            self.configuration = settings.ACCOUNT_VISIBILITY_CONFIGURATION

        # Don't pass the 'admin_fields' arg up to the superclass
        self.admin_fields = kwargs.pop('admin_fields', False)

        # Instantiate the superclass normally
        super(AccountFullUserProfileReadOnlySerializer, self).__init__(*args, **kwargs)

    def to_native(self, user):
        """
        Overwrite to_native to handle custom logic since we are serializing two models as one here
        :param user: User object
        :return: Dict serialized account
        """
        profile = user.profile

        data = {
            "username": user.username,
            "url": ''.join([
                'http://',
                get_current_site(None).domain,
                reverse('accounts_api', kwargs={'username': user.username})
            ]),
            "email": user.email,
            "date_joined": user.date_joined,
            "is_active": user.is_active,
            "bio": profile.bio,
            "country": profile.country.code,
            "profile_image": self._get_profile_image(profile, user),
            "time_zone": None,
            "language_proficiencies": LanguageProficiencySerializer(
                profile.language_proficiencies.all(),
                many=True
            ).data,
            "name": profile.name,
            "gender": profile.gender,
            "goals": profile.goals,
            "year_of_birth": profile.year_of_birth,
            "level_of_education": profile.level_of_education,
            "mailing_address": profile.mailing_address,
            "requires_parental_consent": profile.requires_parental_consent(),
        }

        return self._filter_fields(
            self._visible_fields(profile, user),
            data
        )
    def _get_profile_image(self, user_profile, user):
        """ Returns metadata about a user's profile image. """
        data = {'has_image': user_profile.has_profile_image}
        urls = get_profile_image_urls_for_user(user)
        data.update({
            '{image_key_prefix}_{size}'.format(image_key_prefix=PROFILE_IMAGE_KEY_PREFIX, size=size_display_name): url
            for size_display_name, url in urls.items()
        })

        # add absolute path to image urls if it is not already there
        for key, value in data.items():
            if key.startswith(PROFILE_IMAGE_KEY_PREFIX):
                data[key] = ''.join(["http://", get_current_site(None).domain, value])

        return data

    def _visible_fields(self, user_profile, user):
        """
        Return what fields should be visible based on user settings

        :param user_profile: User profile object
        :param user: User object
        :return: whitelist List of fields to be shown
        """

        if self.admin_fields:
           return self.configuration.get('admin_fields')

        profile_visibility = self._get_profile_visibility(user_profile, user)

        if profile_visibility == ALL_USERS_VISIBILITY:
            return self.configuration.get('shareable_fields')
        else:
            return self.configuration.get('public_fields')

    def _get_profile_visibility(self, user_profile, user):
        """Returns the visibility level for the specified user profile."""
        if user_profile.requires_parental_consent():
            return PRIVATE_VISIBILITY

        # Calling UserPreference directly because the requesting user may be different from existing_user
        # (and does not have to be is_staff).
        profile_privacy = UserPreference.get_value(user, ACCOUNT_VISIBILITY_PREF_KEY)
        return profile_privacy if profile_privacy else self.configuration.get('default_visibility')

    def _filter_fields(self, field_whitelist, serialized_account):
        """
        Filter serialized account Dict to only include whitelisted keys
        """
        visible_serialized_account = {}

        for field_name in field_whitelist:
            visible_serialized_account[field_name] = serialized_account.get(field_name, None)

        return visible_serialized_account

class AccountUserSerializer(serializers.HyperlinkedModelSerializer, ReadOnlyFieldsSerializerMixin):
    """
    Class that serializes the portion of User model needed for account information.
    """
    class Meta(object):  # pylint: disable=missing-docstring
        model = User
        fields = ("username", "email", "date_joined", "is_active")
        read_only_fields = ("username", "email", "date_joined", "is_active")
        explicit_read_only_fields = ()


class AccountLegacyProfileSerializer(serializers.HyperlinkedModelSerializer, ReadOnlyFieldsSerializerMixin):
    """
    Class that serializes the portion of UserProfile model needed for account information.
    """
    profile_image = serializers.SerializerMethodField("get_profile_image")
    requires_parental_consent = serializers.SerializerMethodField("get_requires_parental_consent")
    language_proficiencies = LanguageProficiencySerializer(many=True, allow_add_remove=True, required=False)

    class Meta(object):  # pylint: disable=missing-docstring
        model = UserProfile
        fields = (
            "name", "gender", "goals", "year_of_birth", "level_of_education", "country",
            "mailing_address", "bio", "profile_image", "requires_parental_consent", "language_proficiencies"
        )
        # Currently no read-only field, but keep this so view code doesn't need to know.
        read_only_fields = ()
        explicit_read_only_fields = ("profile_image", "requires_parental_consent")

    def validate_name(self, attrs, source):
        """ Enforce minimum length for name. """
        if source in attrs:
            new_name = attrs[source].strip()
            if len(new_name) < NAME_MIN_LENGTH:
                raise serializers.ValidationError(
                    "The name field must be at least {} characters long.".format(NAME_MIN_LENGTH)
                )
            attrs[source] = new_name

        return attrs

    def validate_language_proficiencies(self, attrs, source):
        """ Enforce all languages are unique. """
        language_proficiencies = [language for language in attrs.get(source, [])]
        unique_language_proficiencies = set(language.code for language in language_proficiencies)
        if len(language_proficiencies) != len(unique_language_proficiencies):
            raise serializers.ValidationError("The language_proficiencies field must consist of unique languages")
        return attrs

    def transform_gender(self, user_profile, value):
        """ Converts empty string to None, to indicate not set. Replaced by to_representation in version 3. """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_country(self, user_profile, value):
        """ Converts empty string to None, to indicate not set. Replaced by to_representation in version 3. """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_level_of_education(self, user_profile, value):
        """ Converts empty string to None, to indicate not set. Replaced by to_representation in version 3. """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    def transform_bio(self, user_profile, value):
        """ Converts empty string to None, to indicate not set. Replaced by to_representation in version 3. """
        return AccountLegacyProfileSerializer.convert_empty_to_None(value)

    @staticmethod
    def convert_empty_to_None(value):
        """ Helper method to convert empty string to None (other values pass through). """
        return None if value == "" else value

    def get_profile_image(self, user_profile):
        """ Returns metadata about a user's profile image. """
        data = {'has_image': user_profile.has_profile_image}
        urls = get_profile_image_urls_for_user(user_profile.user)
        data.update({
            '{image_key_prefix}_{size}'.format(image_key_prefix=PROFILE_IMAGE_KEY_PREFIX, size=size_display_name): url
            for size_display_name, url in urls.items()
        })
        return data

    def get_requires_parental_consent(self, user_profile):
        """ Returns a boolean representing whether the user requires parental controls.  """
        return user_profile.requires_parental_consent()
