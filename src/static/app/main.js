// Entry module: registers the page components and starts Alpine (CSP build,
// so attribute expressions run without eval).

import Alpine from '../vendor/alpine-csp-3.17.5/module.esm.min.js';
import browser from './browser.js';
import members from './members.js';
import review from './review.js';
import setup from './setup.js';

Alpine.data('browser', browser);
Alpine.data('members', members);
Alpine.data('review', review);
Alpine.data('setup', setup);
window.Alpine = Alpine;
Alpine.start();
