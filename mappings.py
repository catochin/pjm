import requests
from lxml import html
from enum import Enum
import re

class MappingsType(Enum):
    MOJANG = 'mojang'
    YARN = 'yarn'
    INTERMEDIARY = 'intermediary'
    SEARGE = 'searge'

class InvalidMappingTypeError(Exception):
    def __init__(self, version, mapping_type):
        message = f'For versions less than 1.15, use only Searge mappings! Version: {version}, Mapping Type: {mapping_type}'
        super().__init__(message)

class Mappings:
    # Regex patterns to identify the style of names for each mapping type
    NAME_PATTERNS = {
        MappingsType.MOJANG: re.compile(r'^(net\.minecraft\.|com\.mojang\.)([a-zA-Z0-9_$.]+)$'),
        MappingsType.YARN: re.compile(r'^(net\.minecraft\.|com\.mojang\.)([a-zA-Z0-9_$.]+Client|[a-zA-Z0-9_$.]+Impl|.*[A-Z].*)$'),
        MappingsType.INTERMEDIARY: re.compile(r'^net\.minecraft\.class_[0-9]+$'),
        MappingsType.SEARGE: re.compile(r'^(net\.minecraft\.|com\.mojang\.)([a-zA-Z0-9_$.]+)$|^(field_|method_|func_)[0-9]+_[a-zA-Z]$'), # Searge can be class names OR field_/method_ patterns
    }

    # Common class for the cell containing the actual name text
    POTENTIAL_NAME_CELL_CLASS = 'F'

    def __init__(self, version, mapping_type=MappingsType.MOJANG):
        try:
            minor_version_str = version.split('.')[1]
            minor_version = int(minor_version_str)
            if minor_version < 15 and mapping_type != MappingsType.SEARGE:
                raise InvalidMappingTypeError(version, mapping_type)
        except (IndexError, ValueError) as e:
            print(f"Warning: Could not parse minor version from '{version}'. Error: {e}")

        self.version = version
        self.mapping_type_requested = mapping_type
        self.field_mappings = {}
        self.method_mappings = {}
        self.mapping_class_name = None
        self.obfuscated_class_name = None

        # Dynamically detected selectors
        self.detected_selectors = {
            'class_name_markers': {}, # To store {MappingsType.MOJANG: 'D G', ...}
            'obfuscated_class_marker': None,
            'searge_class_marker': None, # Separate marker for Searge class names
            'field_method_table_class': None,
            'name_container_cell_class': self.POTENTIAL_NAME_CELL_CLASS
        }

    def _detect_selectors(self, tree):
        """
        Tries to dynamically determine the CSS classes used for marking different mapping types
        based on the content and structure of the HTML.
        """
        print("Attempting to detect selectors...")

        # Find definition tables
        definition_tables = tree.xpath(f"//table[.//td[@class and following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']]]")

        if not definition_tables:
            print("Warning: Could not find any potential class definition tables.")
            return

        class_def_table = definition_tables[0]
        rows = class_def_table.xpath('.//tr')
        found_types_for_class_names = set()

        for row in rows:
            cells = row.xpath('./td')
            if len(cells) == 2:
                marker_cell = cells[0]
                name_cell = cells[1]

                marker_class = marker_cell.get('class')
                name_cell_class = name_cell.get('class')

                if not marker_class or name_cell_class != self.POTENTIAL_NAME_CELL_CLASS:
                    continue

                class_name_text = name_cell.text_content().strip()
                if not class_name_text:
                    continue

                # Detect obfuscated names (short, typically 1-4 characters)
                if len(class_name_text) <= 4 and re.match(r'^[a-zA-Z]{1,4}$', class_name_text):
                    if MappingsType.SEARGE not in found_types_for_class_names:
                        self.detected_selectors['obfuscated_class_marker'] = marker_class
                        found_types_for_class_names.add(MappingsType.SEARGE)
                        print(f"  Detected Obfuscated class marker: '{marker_class}' for name '{class_name_text}'")

                # Detect Searge class names (look for full class names that are Searge style)
                elif class_name_text.startswith(('net.minecraft.', 'com.mojang.')):
                    # This is a full class name, determine its type
                    if 'Client' in class_name_text or 'Impl' in class_name_text:
                        # Likely Yarn
                        if MappingsType.YARN not in found_types_for_class_names:
                            self.detected_selectors['class_name_markers'][MappingsType.YARN] = marker_class
                            found_types_for_class_names.add(MappingsType.YARN)
                            print(f"  Detected YARN class marker: '{marker_class}' for name '{class_name_text}'")
                    elif 'class_' in class_name_text:
                        # Intermediary
                        if MappingsType.INTERMEDIARY not in found_types_for_class_names:
                            self.detected_selectors['class_name_markers'][MappingsType.INTERMEDIARY] = marker_class
                            found_types_for_class_names.add(MappingsType.INTERMEDIARY)
                            print(f"  Detected INTERMEDIARY class marker: '{marker_class}' for name '{class_name_text}'")
                    else:
                        # Could be Mojang or Searge class name
                        # Try to distinguish - Searge class names are often the same as Mojang but in a different context
                        # For now, assume first full class name is Mojang, second is Searge
                        if MappingsType.MOJANG not in found_types_for_class_names:
                            self.detected_selectors['class_name_markers'][MappingsType.MOJANG] = marker_class
                            found_types_for_class_names.add(MappingsType.MOJANG)
                            print(f"  Detected MOJANG class marker: '{marker_class}' for name '{class_name_text}'")
                        elif 'searge_class_marker' not in self.detected_selectors or self.detected_selectors['searge_class_marker'] is None:
                            self.detected_selectors['searge_class_marker'] = marker_class
                            self.detected_selectors['class_name_markers'][MappingsType.SEARGE] = marker_class
                            print(f"  Detected SEARGE class marker: '{marker_class}' for name '{class_name_text}'")

        # Detect Field/Method table class
        field_summary_h4 = tree.xpath("//h4[text()='Field summary']")
        common_table_class = None
        if field_summary_h4:
            next_table = field_summary_h4[0].xpath("./following-sibling::table[1]")
            if next_table and next_table[0].get('class'):
                common_table_class = next_table[0].get('class')
                self.detected_selectors['field_method_table_class'] = common_table_class
                print(f"  Detected Field/Method table class: '{common_table_class}'")

        if not common_table_class:
            method_summary_h4 = tree.xpath("//h4[text()='Method summary']")
            if method_summary_h4:
                next_table = method_summary_h4[0].xpath("./following-sibling::table[1]")
                if next_table and next_table[0].get('class'):
                    common_table_class = next_table[0].get('class')
                    self.detected_selectors['field_method_table_class'] = common_table_class
                    print(f"  Detected Field/Method table class (via method summary): '{common_table_class}'")

        print("Selector detection finished.")

    def fetch(self, class_path):
        url = f'https://mappings.dev/{self.version}/{class_path.replace(".", "/")}.html'
        response = requests.get(url)
        response.raise_for_status()
        tree = html.fromstring(response.content)

        self._detect_selectors(tree)

        # Get the appropriate markers
        obf_marker = self.detected_selectors['obfuscated_class_marker']
        if not obf_marker:
            raise ValueError("Failed to detect obfuscated class name marker. Cannot parse class names.")

        # For class names, determine which marker to use
        if self.mapping_type_requested == MappingsType.SEARGE:
            # For Searge, use the Searge class marker if available, otherwise fall back to Mojang
            requested_type_marker_class = (self.detected_selectors['searge_class_marker'] or
                                         self.detected_selectors['class_name_markers'].get(MappingsType.MOJANG))
        else:
            requested_type_marker_class = self.detected_selectors['class_name_markers'].get(self.mapping_type_requested)

        if not requested_type_marker_class:
            raise ValueError(f"Failed to detect marker for requested mapping type '{self.mapping_type_requested.name}'.")

        # Extract class names
        try:
            obf_class_marker_td = tree.xpath(f"(//td[@class='{obf_marker}'])[1]")[0]
            class_name_definition_table = obf_class_marker_td.xpath('./ancestor::table[1]')[0]
        except IndexError:
            raise ValueError("Could not re-find the class name definition table using detected markers.")

        try:
            obfuscated_class_element = class_name_definition_table.xpath(f".//td[@class='{obf_marker}']/following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']")[0]
            self.obfuscated_class_name = obfuscated_class_element.text_content().strip()
        except IndexError:
            raise ValueError(f"Could not find obfuscated class name using detected marker '{obf_marker}'.")

        try:
            mapping_class_element = class_name_definition_table.xpath(f".//td[@class='{requested_type_marker_class}']/following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']")[0]
            self.mapping_class_name = mapping_class_element.text_content().strip()
        except IndexError:
            raise ValueError(f"Could not find mapping class name for type '{self.mapping_type_requested.name}' using detected marker '{requested_type_marker_class}'.")

        # Process field and method tables
        fm_table_classes_str = self.detected_selectors['field_method_table_class']
        if not fm_table_classes_str:
            print("Warning: Field/Method table class not detected. Skipping field/method parsing.")
        else:
            class_conditions = []
            for cls in fm_table_classes_str.split():
                if cls.strip():
                    class_conditions.append(f"contains(concat(' ', normalize-space(@class), ' '), ' {cls.strip()} ')")

            xpath_fm_table_selector_conditions = " and ".join(class_conditions)
            xpath_fm_table_selector = f"table[{xpath_fm_table_selector_conditions}]"

            # Process fields
            h4_field_summary = tree.xpath("//h4[text()='Field summary']")
            if h4_field_summary:
                fields_table_candidates = h4_field_summary[0].xpath(f"./following-sibling::{xpath_fm_table_selector}[1]")
                if fields_table_candidates:
                    self._process_member_table(fields_table_candidates[0], self.field_mappings)

            # Process methods
            h4_method_summary = tree.xpath("//h4[text()='Method summary']")
            if h4_method_summary:
                methods_table_candidates = h4_method_summary[0].xpath(f"./following-sibling::{xpath_fm_table_selector}[1]")
                if methods_table_candidates:
                    self._process_member_table(methods_table_candidates[0], self.method_mappings)

        return self.get()

    def _process_member_table(self, table_element, mapping_dict):
        obf_member_marker = self.detected_selectors['obfuscated_class_marker']

        # For members (fields/methods), determine the appropriate marker
        if self.mapping_type_requested == MappingsType.SEARGE:
            # Look for Searge-style field_/method_ patterns
            # First try to find a dedicated Searge marker, otherwise use obfuscated
            requested_type_member_marker = self.detected_selectors['searge_class_marker']
            if not requested_type_member_marker:
                requested_type_member_marker = obf_member_marker
        else:
            requested_type_member_marker = self.detected_selectors['class_name_markers'].get(self.mapping_type_requested)

        if not obf_member_marker:
            print("Warning: Obfuscated member marker not available. Cannot parse members.")
            return
        if not requested_type_member_marker:
            print(f"Warning: Marker for requested type '{self.mapping_type_requested.name}' for members not available.")
            return

        rows = table_element.xpath('./tbody/tr')
        for row in rows:
            cells = row.xpath('./td')
            if len(cells) < 2:
                continue

            name_container_td = cells[1]

            # Look for Searge-style names (field_XXXXX_X or method_XXXXX_X patterns)
            if self.mapping_type_requested == MappingsType.SEARGE:
                # Check all possible markers for Searge-style names
                all_name_elements = name_container_td.xpath(f".//td[@class]/following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']")
                searge_name = None
                obfuscated_name = None

                for name_element in all_name_elements:
                    name_text = name_element.text_content().strip()
                    if '(' in name_text:
                        name_text = name_text.split('(')[0]

                    # Check if this looks like a Searge name
                    if re.match(r'^(field_|method_|func_)[0-9]+_[a-zA-Z]$', name_text):
                        searge_name = name_text
                    elif len(name_text) <= 4 and re.match(r'^[a-zA-Z]{1,4}$', name_text):
                        obfuscated_name = name_text

                if searge_name and obfuscated_name:
                    mapping_dict[searge_name] = obfuscated_name
            else:
                # Standard processing for other mapping types
                mapped_name_elements = name_container_td.xpath(f".//td[@class='{requested_type_member_marker}']/following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']")
                obfuscated_name_elements = name_container_td.xpath(f".//td[@class='{obf_member_marker}']/following-sibling::td[@class='{self.POTENTIAL_NAME_CELL_CLASS}']")

                if mapped_name_elements and obfuscated_name_elements:
                    mapping_name = mapped_name_elements[0].text_content().strip()
                    obfuscated_name = obfuscated_name_elements[0].text_content().strip()

                    if '(' in mapping_name:
                        mapping_name = mapping_name.split('(')[0]
                    if '(' in obfuscated_name:
                        obfuscated_name = obfuscated_name.split('(')[0]

                    mapping_dict[mapping_name] = obfuscated_name

    def get(self):
        return {
            "class_name": self.mapping_class_name,
            "obfuscated_class_name": self.obfuscated_class_name,
            "fields": self.field_mappings,
            "methods": self.method_mappings
        }
