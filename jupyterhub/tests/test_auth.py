"""Tests for PAM authentication"""

# Copyright (c) Jupyter Development Team.
# Distributed under the terms of the Modified BSD License.

import os
from unittest import mock

import pytest
from requests import HTTPError

from jupyterhub import auth, crypto, orm

from .mocking import MockPAMAuthenticator, MockStructGroup, MockStructPasswd
from .test_api import add_user

@pytest.mark.gen_test
def test_pam_auth():
    authenticator = MockPAMAuthenticator()
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'match',
        'password': 'match',
    })
    assert authorized['name'] == 'match'

    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'match',
        'password': 'nomatch',
    })
    assert authorized is None

    # Account check is on by default for increased security
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'notallowedmatch',
        'password': 'notallowedmatch',
    })
    assert authorized is None


@pytest.mark.gen_test
def test_pam_auth_account_check_disabled():
    authenticator = MockPAMAuthenticator(check_account=False)
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'allowedmatch',
        'password': 'allowedmatch',
    })
    assert authorized['name'] == 'allowedmatch'

    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'notallowedmatch',
        'password': 'notallowedmatch',
    })
    assert authorized['name'] == 'notallowedmatch'


@pytest.mark.gen_test
def test_pam_auth_admin_groups():
    jh_users = MockStructGroup('jh_users', ['group_admin', 'also_group_admin', 'override_admin', 'non_admin'], 1234)
    jh_admins = MockStructGroup('jh_admins', ['group_admin'], 5678)
    wheel = MockStructGroup('wheel', ['also_group_admin'], 9999)
    system_groups = [jh_users, jh_admins, wheel]

    group_admin = MockStructPasswd('group_admin', 1234)
    also_group_admin = MockStructPasswd('also_group_admin', 1234)
    override_admin = MockStructPasswd('override_admin', 1234)
    non_admin = MockStructPasswd('non_admin', 1234)
    system_users = [group_admin, also_group_admin, override_admin, non_admin]

    user_group_map = {
        'group_admin': [jh_users, jh_admins],
        'also_group_admin': [jh_users, wheel],
        'override_admin': [jh_users],
        'non_admin': [jh_users]
    }

    def getgrnam(name):
        return [x for x in system_groups if x.gr_name == name][0]

    def getpwnam(name):
        return [x for x in system_users if x.pw_name == name][0]
    
    def getgrouplist(name, group):
        return user_group_map[name]

    authenticator = MockPAMAuthenticator(admin_groups={'jh_admins', 'wheel'},
                                         admin_users={'override_admin'})

    # Check admin_group applies as expected
    with mock.patch.multiple(authenticator,
                             _getgrnam=getgrnam,
                             _getpwnam=getpwnam,
                             _getgrouplist=getgrouplist):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'group_admin',
            'password': 'group_admin'
        })
    assert authorized['name'] == 'group_admin'
    assert authorized['admin'] is True

    # Check multiple groups work, just in case.
    with mock.patch.multiple(authenticator,
                             _getgrnam=getgrnam,
                             _getpwnam=getpwnam,
                             _getgrouplist=getgrouplist):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'also_group_admin',
            'password': 'also_group_admin'
        })
    assert authorized['name'] == 'also_group_admin'
    assert authorized['admin'] is True

    # Check admin_users still applies correctly
    with mock.patch.multiple(authenticator,
                             _getgrnam=getgrnam,
                             _getpwnam=getpwnam,
                             _getgrouplist=getgrouplist):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'override_admin',
            'password': 'override_admin'
        })
    assert authorized['name'] == 'override_admin'
    assert authorized['admin'] is True

    # Check it doesn't admin everyone
    with mock.patch.multiple(authenticator,
                             _getgrnam=getgrnam,
                             _getpwnam=getpwnam,
                             _getgrouplist=getgrouplist):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'non_admin',
            'password': 'non_admin'
        })
    assert authorized['name'] == 'non_admin'
    assert authorized['admin'] is False


@pytest.mark.gen_test
def test_pam_auth_whitelist():
    authenticator = MockPAMAuthenticator(whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'kaylee',
        'password': 'kaylee',
    })
    assert authorized['name'] == 'kaylee'

    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'wash',
        'password': 'nomatch',
    })
    assert authorized is None

    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'mal',
        'password': 'mal',
    })
    assert authorized is None


@pytest.mark.gen_test
def test_pam_auth_group_whitelist():
    def getgrnam(name):
        return MockStructGroup('grp', ['kaylee'])

    authenticator = MockPAMAuthenticator(group_whitelist={'group'})

    with mock.patch.object(authenticator, '_getgrnam', getgrnam):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'kaylee',
            'password': 'kaylee',
        })
    assert authorized['name'] == 'kaylee'

    with mock.patch.object(authenticator, '_getgrnam', getgrnam):
        authorized = yield authenticator.get_authenticated_user(None, {
            'username': 'mal',
            'password': 'mal',
        })
    assert authorized is None


@pytest.mark.gen_test
def test_pam_auth_blacklist():
    # Null case compared to next case
    authenticator = MockPAMAuthenticator()
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'wash',
        'password': 'wash',
    })
    assert authorized['name'] == 'wash'

    # Blacklist basics
    authenticator = MockPAMAuthenticator(blacklist={'wash'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'wash',
        'password': 'wash',
    })
    assert authorized is  None

    # User in both white and blacklists: default deny.  Make error someday?
    authenticator = MockPAMAuthenticator(blacklist={'wash'}, whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'wash',
        'password': 'wash',
    })
    assert authorized is None

    # User not in blacklist can log in
    authenticator = MockPAMAuthenticator(blacklist={'wash'}, whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'kaylee',
        'password': 'kaylee',
    })
    assert authorized['name'] == 'kaylee'

    # User in whitelist, blacklist irrelevent
    authenticator = MockPAMAuthenticator(blacklist={'mal'}, whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'wash',
        'password': 'wash',
    })
    assert authorized['name'] == 'wash'

    # User in neither list
    authenticator = MockPAMAuthenticator(blacklist={'mal'}, whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'simon',
        'password': 'simon',
    })
    assert authorized is None

    # blacklist == {}
    authenticator = MockPAMAuthenticator(blacklist=set(), whitelist={'wash', 'kaylee'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'kaylee',
        'password': 'kaylee',
    })
    assert authorized['name'] == 'kaylee'


@pytest.mark.gen_test
def test_pam_auth_no_such_group():
    authenticator = MockPAMAuthenticator(group_whitelist={'nosuchcrazygroup'})
    authorized = yield authenticator.get_authenticated_user(None, {
        'username': 'kaylee',
        'password': 'kaylee',
    })
    assert authorized is None


@pytest.mark.gen_test
def test_wont_add_system_user():
    user = orm.User(name='lioness4321')
    authenticator = auth.PAMAuthenticator(whitelist={'mal'})
    authenticator.create_system_users = False
    with pytest.raises(KeyError):
        yield authenticator.add_user(user)


@pytest.mark.gen_test
def test_cant_add_system_user():
    user = orm.User(name='lioness4321')
    authenticator = auth.PAMAuthenticator(whitelist={'mal'})
    authenticator.add_user_cmd = ['jupyterhub-fake-command']
    authenticator.create_system_users = True

    class DummyFile:
        def read(self):
            return b'dummy error'

    class DummyPopen:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs
            self.returncode = 1
            self.stdout = DummyFile()

        def wait(self):
            return

    with mock.patch.object(auth, 'Popen', DummyPopen):
        with pytest.raises(RuntimeError) as exc:
            yield authenticator.add_user(user)
        assert str(exc.value) == 'Failed to create system user lioness4321: dummy error'


@pytest.mark.gen_test
def test_add_system_user():
    user = orm.User(name='lioness4321')
    authenticator = auth.PAMAuthenticator(whitelist={'mal'})
    authenticator.create_system_users = True
    authenticator.add_user_cmd = ['echo', '/home/USERNAME']

    record = {}
    class DummyPopen:
        def __init__(self, cmd, *args, **kwargs):
            record['cmd'] = cmd
            self.returncode = 0

        def wait(self):
            return

    with mock.patch.object(auth, 'Popen', DummyPopen):
        yield authenticator.add_user(user)
    assert record['cmd'] == ['echo', '/home/lioness4321', 'lioness4321']


@pytest.mark.gen_test
def test_delete_user():
    user = orm.User(name='zoe')
    a = MockPAMAuthenticator(whitelist={'mal'})

    assert 'zoe' not in a.whitelist
    yield a.add_user(user)
    assert 'zoe' in a.whitelist
    a.delete_user(user)
    assert 'zoe' not in a.whitelist


def test_urls():
    a = auth.PAMAuthenticator()
    logout = a.logout_url('/base/url/')
    login = a.login_url('/base/url')
    assert logout == '/base/url/logout'
    assert login == '/base/url/login'


def test_handlers(app):
    a = auth.PAMAuthenticator()
    handlers = a.get_handlers(app)
    assert handlers[0][0] == '/login'


@pytest.mark.gen_test
def test_auth_state(app, auth_state_enabled):
    """auth_state enabled and available"""
    name = 'kiwi'
    user = add_user(app.db, app, name=name)
    assert user.encrypted_auth_state is None
    cookies = yield app.login_user(name)
    auth_state = yield user.get_auth_state()
    assert auth_state == app.authenticator.auth_state


@pytest.mark.gen_test
def test_auth_admin_non_admin(app):
    """admin should be passed through for non-admin users"""
    name = 'kiwi'
    user = add_user(app.db, app, name=name, admin=False)
    assert user.admin is False
    cookies = yield app.login_user(name)
    assert user.admin is False


@pytest.mark.gen_test
def test_auth_admin_is_admin(app):
    """admin should be passed through for admin users"""
    # Admin user defined in MockPAMAuthenticator.
    name = 'admin'
    user = add_user(app.db, app, name=name, admin=False)
    assert user.admin is False
    cookies = yield app.login_user(name)
    assert user.admin is True


@pytest.mark.gen_test
def test_auth_admin_retained_if_unset(app):
    """admin should be unchanged if authenticator doesn't return admin value"""
    name = 'kiwi'
    # Add user as admin.
    user = add_user(app.db, app, name=name, admin=True)
    assert user.admin is True
    # User should remain unchanged.
    cookies = yield app.login_user(name)
    assert user.admin is True


@pytest.fixture
def auth_state_unavailable(auth_state_enabled):
    """auth_state enabled at the Authenticator level,

    but unavailable due to no crypto keys.
    """
    crypto.CryptKeeper.instance().keys = []
    yield


@pytest.mark.gen_test
def test_auth_state_disabled(app, auth_state_unavailable):
    name = 'driebus'
    user = add_user(app.db, app, name=name)
    assert user.encrypted_auth_state is None
    with pytest.raises(HTTPError):
        cookies = yield app.login_user(name)
    auth_state = yield user.get_auth_state()
    assert auth_state is None


@pytest.mark.gen_test
def test_normalize_names():
    a = MockPAMAuthenticator()
    authorized = yield a.get_authenticated_user(None, {
        'username': 'ZOE',
        'password': 'ZOE',
    })
    assert authorized['name'] == 'zoe'

    authorized = yield a.get_authenticated_user(None, {
        'username': 'Glenn',
        'password': 'Glenn',
    })
    assert authorized['name'] == 'glenn'

    authorized = yield a.get_authenticated_user(None, {
        'username': 'hExi',
        'password': 'hExi',
    })
    assert authorized['name'] == 'hexi'

    authorized = yield a.get_authenticated_user(None, {
        'username': 'Test',
        'password': 'Test',
    })
    assert authorized['name'] == 'test'


@pytest.mark.gen_test
def test_username_map():
    a = MockPAMAuthenticator(username_map={'wash': 'alpha'})
    authorized = yield a.get_authenticated_user(None, {
        'username': 'WASH',
        'password': 'WASH',
    })

    assert authorized['name'] == 'alpha'

    authorized = yield a.get_authenticated_user(None, {
        'username': 'Inara',
        'password': 'Inara',
    })
    assert authorized['name'] == 'inara'


def test_validate_names():
    a = auth.PAMAuthenticator()
    assert a.validate_username('willow')
    assert a.validate_username('giles')
    assert a.validate_username('Test')
    assert a.validate_username('hExi')
    assert a.validate_username('Glenn#Smith!')
    a = auth.PAMAuthenticator(username_pattern='w.*')
    assert not a.validate_username('xander')
    assert a.validate_username('willow')
