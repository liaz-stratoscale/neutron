# Copyright (c) 2014 Thales Services SAS
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import mock
from testtools import matchers

from neutron.common import exceptions as exc
import neutron.db.api as db
from neutron.plugins.common import constants as p_const
from neutron.plugins.ml2 import driver_api as api
from neutron.plugins.ml2.drivers import type_vlan
from neutron.tests import base

PROVIDER_NET = 'phys_net1'
TENANT_NET = 'phys_net2'
VLAN_MIN = 200
VLAN_MAX = 209
NETWORK_VLAN_RANGES = {
    PROVIDER_NET: [],
    TENANT_NET: [(VLAN_MIN, VLAN_MAX)],
}
UPDATED_VLAN_RANGES = {
    PROVIDER_NET: [],
    TENANT_NET: [(VLAN_MIN + 5, VLAN_MAX + 5)],
}


class VlanTypeTest(base.BaseTestCase):

    def setUp(self):
        super(VlanTypeTest, self).setUp()
        db.configure_db()
        self.driver = type_vlan.VlanTypeDriver()
        self.driver.network_vlan_ranges = NETWORK_VLAN_RANGES
        self.driver._sync_vlan_allocations()
        self.session = db.get_session()
        self.addCleanup(db.clear_db)

    def _get_allocation(self, session, segment):
        return session.query(type_vlan.VlanAllocation).filter_by(
            physical_network=segment[api.PHYSICAL_NETWORK],
            vlan_id=segment[api.SEGMENTATION_ID]).first()

    def test_validate_provider_segment(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 1}
        self.assertIsNone(self.driver.validate_provider_segment(segment))

    def test_validate_provider_segment_with_missing_physical_network(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.SEGMENTATION_ID: 1}
        self.assertRaises(exc.InvalidInput,
                          self.driver.validate_provider_segment,
                          segment)

    def test_validate_provider_segment_with_missing_segmentation_id(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET}
        self.assertRaises(exc.InvalidInput,
                          self.driver.validate_provider_segment,
                          segment)

    def test_validate_provider_segment_with_invalid_physical_network(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: 'other_phys_net',
                   api.SEGMENTATION_ID: 1}
        self.assertRaises(exc.InvalidInput,
                          self.driver.validate_provider_segment,
                          segment)

    def test_validate_provider_segment_with_invalid_segmentation_id(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 5000}
        self.assertRaises(exc.InvalidInput,
                          self.driver.validate_provider_segment,
                          segment)

    def test_validate_provider_segment_with_invalid_input(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 1,
                   'invalid': 1}
        self.assertRaises(exc.InvalidInput,
                          self.driver.validate_provider_segment,
                          segment)

    def test_sync_vlan_allocations(self):
        def check_in_ranges(network_vlan_ranges):
            vlan_min, vlan_max = network_vlan_ranges[TENANT_NET][0]
            segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                       api.PHYSICAL_NETWORK: TENANT_NET}

            segment[api.SEGMENTATION_ID] = vlan_min - 1
            self.assertIsNone(
                self._get_allocation(self.session, segment))
            segment[api.SEGMENTATION_ID] = vlan_max + 1
            self.assertIsNone(
                self._get_allocation(self.session, segment))

            segment[api.SEGMENTATION_ID] = vlan_min
            self.assertFalse(
                self._get_allocation(self.session, segment).allocated)
            segment[api.SEGMENTATION_ID] = vlan_max
            self.assertFalse(
                self._get_allocation(self.session, segment).allocated)

        check_in_ranges(NETWORK_VLAN_RANGES)
        self.driver.network_vlan_ranges = UPDATED_VLAN_RANGES
        self.driver._sync_vlan_allocations()
        check_in_ranges(UPDATED_VLAN_RANGES)

    def test_reserve_provider_segment(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 101}
        alloc = self._get_allocation(self.session, segment)
        self.assertIsNone(alloc)
        self.driver.reserve_provider_segment(self.session, segment)
        alloc = self._get_allocation(self.session, segment)
        self.assertTrue(alloc.allocated)

    def test_reserve_provider_segment_already_allocated(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 101}
        self.driver.reserve_provider_segment(self.session, segment)
        self.assertRaises(exc.VlanIdInUse,
                          self.driver.reserve_provider_segment,
                          self.session,
                          segment)

    def test_reserve_provider_segment_in_tenant_pools(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: TENANT_NET,
                   api.SEGMENTATION_ID: VLAN_MIN}
        alloc = self._get_allocation(self.session, segment)
        self.assertFalse(alloc.allocated)
        self.driver.reserve_provider_segment(self.session, segment)
        alloc = self._get_allocation(self.session, segment)
        self.assertTrue(alloc.allocated)

    def test_allocate_tenant_segment(self):
        for __ in range(VLAN_MIN, VLAN_MAX + 1):
            segment = self.driver.allocate_tenant_segment(self.session)
            alloc = self._get_allocation(self.session, segment)
            self.assertTrue(alloc.allocated)
            vlan_id = segment[api.SEGMENTATION_ID]
            self.assertThat(vlan_id, matchers.GreaterThan(VLAN_MIN - 1))
            self.assertThat(vlan_id, matchers.LessThan(VLAN_MAX + 1))
            self.assertEqual(TENANT_NET, segment[api.PHYSICAL_NETWORK])

    def test_allocate_tenant_segment_no_available(self):
        for __ in range(VLAN_MIN, VLAN_MAX + 1):
            self.driver.allocate_tenant_segment(self.session)
        segment = self.driver.allocate_tenant_segment(self.session)
        self.assertIsNone(segment)

    def test_release_segment(self):
        segment = self.driver.allocate_tenant_segment(self.session)
        self.driver.release_segment(self.session, segment)
        alloc = self._get_allocation(self.session, segment)
        self.assertFalse(alloc.allocated)

    def test_release_segment_unallocated(self):
        segment = {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                   api.PHYSICAL_NETWORK: PROVIDER_NET,
                   api.SEGMENTATION_ID: 101}
        with mock.patch.object(type_vlan.LOG, 'warning') as log_warn:
            self.driver.release_segment(self.session, segment)
            log_warn.assert_called_once_with(
                "No vlan_id %(vlan_id)s found on physical network "
                "%(physical_network)s",
                {'vlan_id': 101, 'physical_network': PROVIDER_NET})