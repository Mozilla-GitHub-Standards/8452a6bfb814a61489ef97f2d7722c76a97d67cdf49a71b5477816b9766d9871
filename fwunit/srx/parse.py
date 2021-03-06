# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

import lxml.etree as ET
from . import show
from fwunit.ip import IP, IPSet
from logging import getLogger
import time

log = getLogger(__name__)


def strip_namespaces(root):
    """Strip namespaces from all elements in the XML document.  Juniper adds
    version-specific namespaces to route documents, so this makes parsing them
    a lot easier"""
    # from http://stackoverflow.com/questions/18159221/remove-namespace-and-prefix-from-xml-in-python-using-lxml
    for elem in root.getiterator():
        if not hasattr(elem.tag, 'find'):
            continue
        i = elem.tag.find('}')
        if i >= 0:
            elem.tag = elem.tag[i+1:]
    return root

class Policy(object):

    def __init__(self):
        #: policy name
        self.name = None

        #: source zone name for this policy, or None for the global policy
        self.from_zone = None

        #: destination zone name for this policy
        self.to_zone = None

        #: boolean, true if the policy is enabled
        self.enabled = None

        #: policy sequence number
        self.sequence = None

        #: source addresses (by name) for the policy
        self.source_addresses = []

        #: destination addresses (by name) for the policy
        self.destination_addresses = []

        #: applications (name) for the policy
        self.applications = []

        #: 'permit' or 'deny'
        self.action = None

    def __str__(self):
        return ("%(action)s %(from_zone)s:%(source_addresses)r -> "
                "%(to_zone)s:%(destination_addresses)r : %(applications)s") % self.__dict__

    @classmethod
    def _from_xml(cls, from_zone, to_zone, policy_information_elt):
        pol = cls()
        pie = policy_information_elt
        pol.name = pie.find('./policy-name').text
        pol.from_zone = from_zone
        pol.to_zone = to_zone
        pol.enabled = pie.find('./policy-state').text == 'enabled'
        pol.sequence = int(pie.find('./policy-sequence-number').text)
        pol.source_addresses = [
            pol._parse_address(e) for e in pie.findall('./source-addresses/*')]
        pol.destination_addresses = [
            pol._parse_address(e) for e in pie.findall('./destination-addresses/*')]
        pol.applications = [
            pol._parse_application(e) for e in pie.findall('./applications/application')]
        pol.action = pie.find('./policy-action/action-type').text
        return pol

    def _parse_address(self, elt):
        addrname = elt.find('./address-name')
        return addrname.text

    def _parse_application(self, elt):
        appname = elt.find('./application-name')
        return appname.text


class Route(object):

    """A route from the firewall's routing table"""

    def __init__(self):
        #: IPSet based on the route destination
        self.destination = None

        #: interface to which traffic is forwarded (via or local)
        self.interface = None

        #: true if this destination is local (no next-hop IP)
        self.is_local = None

        #: true if this is a "Reject" (blackhole) route
        self.reject = False

    def __str__(self):
        return "%s via %s" % (self.destination, self.interface)

    @classmethod
    def _from_xml(cls, rt_elt):
        valid = False
        route = cls()
        route.destination = IP(rt_elt.find('rt-destination').text)
        for entry in rt_elt.findall('rt-entry'):
            if entry.findall('.//current-active'):
                vias = entry.findall('.//via')
                if vias:
                    route.interface = vias[0].text
                    valid = True
                route.is_local = not bool(
                    entry.findall('.//to'))
                nh_types = entry.findall('.//nh-type')
                if nh_types:
                    if nh_types[0].text == 'Reject':
                        route.reject = True
                        valid = True

        # don't pretend blackholes are local
        if route.reject:
            route.is_local = False

        # only return a Route if we found something useful
        if valid:
            return route


def _parse_addrbook(addrbook):
    addresses = {}
    for addr in addrbook:
        name = addr.findtext('name')
        if addr.tag == 'address':
            ip = IPSet([IP(addr.findtext('ip-prefix'))])
        else:  # note: assumes address-sets follow addresses
            ip = IPSet()
            for setaddr in addr.findall('address'):
                setname = setaddr.findtext('name')
                ip += addresses[setname]
        addresses[name] = ip
    return addresses

_default_addresses = {
    'any': IPSet([IP('0.0.0.0/0')]),
    'any-ipv4': IPSet([IP('0.0.0.0/0')]),
    # fwunit doesn't handle ipv6, so this is an empty set
    'any-ipv6': IPSet([]),
}

class Zone(object):

    """Parse out zone names and the corresponding interfaces"""

    def __init__(self):
        #: list of interface names
        self.interfaces = []

        #: name -> ipset, based on the zone's address book
        self.addresses = _default_addresses.copy()

    def __str__(self):
        return "%s on %s" % (self.name, self.interfaces)

    @classmethod
    def _from_xml(cls, security_zone_elt):
        zone = cls()
        sze = security_zone_elt
        zone.name = sze.find('name').text

        # interfaces
        for itfc in sze.findall('.//interfaces/name'):
            zone.interfaces.append(itfc.text)

        # address book
        addrbook = sze.find('address-book') 
        if addrbook is not None:
            zone.addresses.update(_parse_addrbook(addrbook))
        return zone


class AddressBook(object):
    """Parse named address books"""
    def __init__(self):
        #: list of zone names
        self.attaches = []

        #: name -> ipset, based on the zone's address book
        self.addresses = _default_addresses.copy()

        #: [name], list of attached zone names
        self.attaches = []

    def __str__(self):
        return self.name

    @classmethod
    def _from_xml(cls, address_book_elt):
        addrbook = cls()
        abe = address_book_elt
        addrbook.name = abe.find('name').text

        # address book
        for elt in abe:
            if elt.tag == 'name':
                addrbook.name = elt.text
            elif elt.tag == 'address':
                ip = IPSet([IP(elt.findtext('ip-prefix'))])
                name = elt.findtext('name')
                addrbook.addresses[name] = ip
            elif elt.tag == 'address-set':
                # note: assumes address-sets follow addresses
                ip = IPSet()
                for setaddr in elt.findall('address'):
                    setname = setaddr.findtext('name')
                    ip += addrbook.addresses[setname]
                name = elt.findtext('name')
                addrbook.addresses[name] = ip
            elif elt.tag == 'attach':
                attaches = []
                for z in elt:
                    attaches.append(z.findtext('name'))
                addrbook.attaches = attaches

        return addrbook


class Firewall(object):

    def parse(self, cfg):
        ssh_connection = show.Connection(cfg)

        #: list of security zones
        self.zones = self._parse_zones(ssh_connection)

        #: list of Policy instances
        self.policies = self._parse_policies(ssh_connection)

        #: list of Route instances from 'inet.0'
        self.routes = self._parse_routes(ssh_connection)

        #: list of AddressBook instances
        self.address_books = self._parse_address_books(ssh_connection)

    def _parse_policies(self, ssh_connection):
        policies = []
        zone_names = [z.name for z in self.zones]
        num_downloads = len(zone_names) ** 2
        count = 0
        for from_zone in zone_names:
            for to_zone in zone_names:
                dl_start = time.time()
                log.info(
                    "downloading policies from-zone %s to-zone %s (%3.0f%%)",
                    from_zone, to_zone, (100 * count / num_downloads))
                count += 1
                policies_xml = ssh_connection.show(
                    'security policies from-zone %s to-zone %s' % (from_zone, to_zone))
                dl_duration = time.time() - dl_start

                log.info(
                    "parsing policies from-zone %s to-zone %s", from_zone, to_zone)
                sspe = ET.fromstring(policies_xml)

                # downloading zones can cause high load on the poor underpowered control
                # plane, so we sleep as long as the query took
                time.sleep(max(0.1, dl_start + 2 * dl_duration - time.time()))

                for elt in sspe.findall('.//security-context'):
                    from_zone = elt.find(
                        './context-information/source-zone-name').text
                    to_zone = elt.find(
                        './context-information/destination-zone-name').text
                    for pol_elt in elt.findall('./policies/policy-information'):
                        policy = Policy._from_xml(from_zone, to_zone, pol_elt)
                        policies.append(policy)

        # look for global policies
        log.info("downloading global policy")
        policies_xml = ssh_connection.show('security policies global')
        spg = ET.fromstring(policies_xml)
        elt = spg.find('.//security-context')
        if elt is not None:
            for pol_elt in elt.findall('./policies/policy-information'):
                policy = Policy._from_xml(None, None, pol_elt)
                policies.append(policy)

        return policies

    def _parse_routes(self, ssh_connection):
        log.info("downloading routes")
        route_xml = ssh_connection.show('route')

        log.info("parsing routes")
        sre = strip_namespaces(ET.fromstring(route_xml))
        routes = []
        for table in sre.findall('.//route-table'):
            if table.findtext('table-name') == 'inet.0':
                for rt_elt in table.findall('rt'):
                    route = Route._from_xml(rt_elt)
                    if route:
                        routes.append(route)
                return routes
        return []

    def _parse_zones(self, ssh_connection):
        log.info("downloading zones")
        zones_xml = ssh_connection.show('configuration security zones')

        log.info("parsing zones")
        scsze = ET.fromstring(zones_xml)
        zones = []
        for sz in scsze.findall('.//security-zone'):
            zones.append(Zone._from_xml(sz))
        return zones

    def _parse_address_books(self, ssh_connection):
        log.info("downloading non-zone address books")
        addrbooks_xml = ssh_connection.show('configuration security address-book')

        log.info("parsing address books")
        csab = ET.fromstring(addrbooks_xml)
        address_books = []
        for ab in csab.findall('.//address-book'):
            address_books.append(AddressBook._from_xml(ab))
        return address_books
