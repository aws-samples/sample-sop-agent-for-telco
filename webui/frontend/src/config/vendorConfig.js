// Vendor configuration for demos
// Change DEMO_VENDOR to customize for different partner demos

export const DEMO_VENDOR = 'Nokia';

export const AVAILABLE_VENDORS = ['Nokia', 'Ericsson', 'Samsung'];

export const VENDOR_DISPLAY_NAMES = {
  Nokia: 'Nokia',
  Ericsson: 'Ericsson',
  Samsung: 'Samsung'
};

export const VENDOR_COLORS = {
  Nokia: '#124191',
  Ericsson: '#0082E6',
  Samsung: '#1428A0'
};

// Get active vendors for current demo (only demo vendor)
export const getActiveVendors = () => [DEMO_VENDOR];

// Get all vendors (for future multi-vendor demos)
export const getAllVendors = () => AVAILABLE_VENDORS;

// Check if vendor is active in current demo
export const isVendorActive = (vendor) => vendor === DEMO_VENDOR;

export default {
  DEMO_VENDOR,
  AVAILABLE_VENDORS,
  VENDOR_DISPLAY_NAMES,
  VENDOR_COLORS,
  getActiveVendors,
  getAllVendors,
  isVendorActive
};
