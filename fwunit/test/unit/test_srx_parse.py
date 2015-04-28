# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import xml.etree.ElementTree as ET
from fwunit.ip import IP, IPSet
from fwunit.srx import parse
from nose.tools import eq_
from fwunit.test.util.srx_xml import route_xml_11_4R6
from fwunit.test.util.srx_xml import zones_empty_xml
from fwunit.test.util.srx_xml import FakeSRX


def parse_xml(xml, elt_path=None):
    elt = parse.strip_namespaces(ET.fromstring(xml))
    if elt_path:
        elt = elt.find(elt_path)
    return elt


def test_parse_zones():
    f = FakeSRX()
    z = f.add_zone('untrust')
    f.add_address(z, 'host1', '9.0.9.1/32')
    f.add_address(z, 'host2', '9.0.9.2/32')
    f.add_address(z, 'puppet', '9.0.9.2/32')
    f.add_address_set(z, 'hosts', 'host1', 'host2')
    f.add_interface(z, 'reth0')

    z = f.add_zone('trust')
    f.add_address(z, 'trustedhost', '10.0.9.2/32')
    f.add_address(z, 'dmz', '10.1.0.0/16')
    f.add_address(z, 'shadow', '10.1.99.99/32')
    f.add_interface(z, 'reth1')

    elt = parse_xml(
        f.fake_show('configuration security zones'), './/security-zone')
    z = parse.Zone._from_xml(elt)
    eq_(z.interfaces, ['reth0'])
    eq_(sorted(z.addresses.keys()),
        sorted(['any', 'any-ipv4', 'any-ipv6', 'host1', 'host2', 'hosts', 'puppet']))
    eq_(z.addresses['any'], IPSet([IP('0.0.0.0/0')]))
    eq_(z.addresses['any-ipv4'], IPSet([IP('0.0.0.0/0')]))
    eq_(z.addresses['any-ipv6'], IPSet([]))


def test_parse_zones_empty():
    elt = parse_xml(zones_empty_xml, './/security-zone')
    z = parse.Zone._from_xml(elt)
    eq_(z.interfaces, [])
    eq_(sorted(z.addresses.keys()), sorted(['any', 'any-ipv6', 'any-ipv4']))


def test_parse_route_11_4R6():
    elt = parse_xml(route_xml_11_4R6, './/rt')
    r = parse.Route._from_xml(elt)
    eq_(r.destination, IP('0.0.0.0/0'))
    eq_(r.interface, 'reth0.10')
    eq_(r.is_local, False)
