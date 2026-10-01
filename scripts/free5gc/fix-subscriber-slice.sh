#!/bin/bash
# =============================================================================
# IND321 - Prune the stale factory S-NSSAI from free5gc subscriber data.
#
# WHY: the free5gc subscriber provisioning seeds each subscriber with the real
# workshop slice (sst=1, sd=112233) AND leaves the factory-default slice
# (sst=1, sd=010203) in the provisioned data. With both slices present the SMF
# can resolve the DNN against the wrong slice, and the packetrusher PDU session
# fails with: "DNN not supported or not subscribed in the slice".
#
# This script removes the stale slice from amData, smData and smfSelection so
# only sd=112233 remains, then the PDU session succeeds and the UE gets an IP.
# Idempotent: safe to run repeatedly. Run on the bastion.
# =============================================================================
set -uo pipefail

NAMESPACE="${NAMESPACE:-free5gc}"
STALE_SD="${STALE_SD:-010203}"            # factory-default slice to remove
STALE_KEY="${STALE_KEY:-01${STALE_SD}}"   # smfSelection key form: sst(2 hex) + sd
CURRENT_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"

if [ -z "${CURRENT_CONTEXT}" ]; then
  echo "ERROR: no current Kubernetes context is configured." >&2
  exit 1
fi

kubectl get --raw=/readyz >/dev/null

MONGO=$(kubectl get pods -n "${NAMESPACE}" | grep mongodb | awk '{print $1}' | head -1)
if [ -z "${MONGO}" ]; then
  echo "ERROR: mongodb pod not found in namespace ${NAMESPACE}"
  exit 1
fi
echo "Using mongo pod: ${MONGO}  (removing stale slice sd=${STALE_SD}, key=${STALE_KEY})"

kubectl exec -n "${NAMESPACE}" "${MONGO}" -- mongosh free5gc --quiet --eval "
  var staleSd = '${STALE_SD}';
  var staleKey = '${STALE_KEY}';
  var am = db.getCollection('subscriptionData.provisionedData.amData').updateMany(
    {}, { \$pull: { 'nssai.defaultSingleNssais': { sst: 1, sd: staleSd } } });
  var sm = db.getCollection('subscriptionData.provisionedData.smData').deleteMany(
    { 'singleNssai.sst': 1, 'singleNssai.sd': staleSd });
  var sel = db.getCollection('subscriptionData.provisionedData.smfSelectionSubscriptionData').updateMany(
    {}, { \$unset: { ['subscribedSnssaiInfos.' + staleKey]: '' } });
  print('amData modified: ' + am.modifiedCount +
        ', smData deleted: ' + sm.deletedCount +
        ', smfSelection modified: ' + sel.modifiedCount);
" 2>&1

echo "Subscriber slice cleanup complete."
