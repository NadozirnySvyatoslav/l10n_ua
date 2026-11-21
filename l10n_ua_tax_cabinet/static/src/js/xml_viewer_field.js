/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, markup, proxy, onWillStart, onWillUpdateProps, useProps } from "@odoo/owl";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class XmlViewerField extends Component {
    static template = "l10n_ua_tax_cabinet.XmlViewerField";
    props = useProps(standardFieldProps);

    setup() {
        this.state = proxy({
            content: '',
            loading: true,
            error: null,
        });

        onWillStart(async () => {
            await this.loadContent();
        });

        onWillUpdateProps(async (nextProps) => {
            if (nextProps.record.resId !== this.props.record.resId) {
                await this.loadContent(nextProps);
            }
        });
    }

    async loadContent(props = this.props) {
        this.state.loading = true;
        this.state.error = null;

        try {
            const resId = props.record.resId;
            const resModel = props.record.resModel;
            const fieldName = props.name;

            if (!resId) {
                this.state.content = '';
                this.state.loading = false;
                return;
            }

            // Fetch the binary content via /web/content as arraybuffer to handle encoding
            const url = `/web/content/${resModel}/${resId}/${fieldName}`;
            const response = await fetch(url);

            if (!response.ok) {
                throw new Error(`Failed to load: ${response.status}`);
            }

            // Get as array buffer to detect and handle encoding
            const buffer = await response.arrayBuffer();
            const content = this.decodeContent(buffer);
            this.state.content = content;
        } catch (e) {
            console.error('XmlViewerField error:', e);
            this.state.error = e.message;
            this.state.content = '';
        }

        this.state.loading = false;
    }

    decodeContent(buffer) {
        const bytes = new Uint8Array(buffer);

        // Try to detect encoding from XML declaration
        // First, read as ASCII to check the declaration
        let asciiHeader = '';
        for (let i = 0; i < Math.min(200, bytes.length); i++) {
            asciiHeader += String.fromCharCode(bytes[i]);
        }

        // Check for encoding in XML declaration
        const encodingMatch = asciiHeader.match(/encoding\s*=\s*["']([^"']+)["']/i);
        let encoding = encodingMatch ? encodingMatch[1].toLowerCase() : null;

        // Map common encoding names
        const encodingMap = {
            'windows-1251': 'windows-1251',
            'cp1251': 'windows-1251',
            'win-1251': 'windows-1251',
            'utf-8': 'utf-8',
            'utf8': 'utf-8',
            'iso-8859-1': 'iso-8859-1',
            'koi8-r': 'koi8-r',
            'koi8-u': 'koi8-u',
        };

        if (encoding && encodingMap[encoding]) {
            encoding = encodingMap[encoding];
        } else {
            // Auto-detect: try UTF-8 first, fall back to windows-1251 for Ukrainian
            encoding = 'utf-8';
        }

        // Try to decode with detected encoding
        try {
            const decoder = new TextDecoder(encoding);
            const text = decoder.decode(buffer);

            // Check if decoding was successful (no replacement characters for valid content)
            if (!text.includes('\ufffd') || encoding === 'utf-8') {
                return text;
            }
        } catch (e) {
            console.log('Decoding with', encoding, 'failed, trying fallback');
        }

        // Fallback: try windows-1251 (common for Ukrainian documents)
        try {
            const decoder = new TextDecoder('windows-1251');
            return decoder.decode(buffer);
        } catch (e) {
            console.log('windows-1251 fallback failed');
        }

        // Last resort: UTF-8 with replacement
        const decoder = new TextDecoder('utf-8', { fatal: false });
        return decoder.decode(buffer);
    }

    get formattedXml() {
        const xml = this.state.content;
        if (!xml) return '';

        // Simple XML formatting with indentation
        let formatted = '';
        let indent = 0;
        const parts = xml.replace(/>\s*</g, '>\n<').split('\n');

        for (let part of parts) {
            part = part.trim();
            if (!part) continue;

            // Decrease indent for closing tags
            if (part.match(/^<\//)) {
                indent = Math.max(0, indent - 1);
            }

            formatted += '  '.repeat(indent) + part + '\n';

            // Increase indent for opening tags (not self-closing, not closing, not processing instruction, not comment)
            if (part.match(/^<[^/!?]/) && !part.match(/\/>$/) && !part.match(/<\/[^>]+>$/)) {
                indent++;
            }
        }

        return formatted;
    }

    get highlightedXml() {
        const xml = this.formattedXml;
        if (!xml) return markup('');

        // Escape HTML entities first
        let escaped = xml
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');

        // Apply syntax highlighting with spans
        // Opening tag name: <tagname or </tagname
        escaped = escaped.replace(/(&lt;\/?)(\w[\w:-]*)/g, '$1<span class="xml-tag">$2</span>');

        // Attributes: name="value" or name='value'
        escaped = escaped.replace(/(\s)([\w:-]+)(=)(&quot;)([^&]*)(&quot;)/g,
            '$1<span class="xml-attr">$2</span>$3<span class="xml-value">$4$5$6</span>');

        // Closing brackets
        escaped = escaped.replace(/(\/?&gt;)/g, '<span class="xml-bracket">$1</span>');

        // XML declaration
        escaped = escaped.replace(/(&lt;\?)(xml)([^?]*)(\?&gt;)/g,
            '<span class="xml-decl">$1$2$3$4</span>');

        return markup(escaped);
    }

    get hasContent() {
        return !!this.state.content;
    }
}

export const xmlViewerField = {
    component: XmlViewerField,
    supportedTypes: ["binary"],
};

registry.category("fields").add("xml_viewer", xmlViewerField);
