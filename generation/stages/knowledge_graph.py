import json
import logging
from typing import Any, Dict, List, Optional, Tuple

from core.types import (
    KGEdge, KGNode, LayerName, LessonKnowledgeGraph)
from core.log import (
    setup_logging, with_logging_context)
from core.helpers import (
    exception_handler, print_json)
from core.clients.gsheet import \
    GoogleSheetsClient
from core.context import APVideoContext as Context
from core.context import prep_content_gen_input

logger = logging.getLogger(__name__)

class KnowledgeGraphConfig:
    """Configuration class for Knowledge Graph generation, handling subject-specific configs."""
    
    # Subject-specific configurations
    SUBJECT_CONFIGS = {
        "AP World History": {
            "SPREADSHEET_CONFIG": {
                'The Global Tapestry': '1v1G-8tnRHvp1g8pSoBBJfzDkM4GTuA-FJnOYPeI0YC4',
                "Networks of Exchange": "1fXJOOH9Xymq-9PDezcsJVBuwsvr_gcTLb-7T5jC8_l8",
                'Land-Based Empires': '1-kw3j00nrPQdLzaFmsjymtU-wdTvCnWfWtOsf_M-opA',
                'Transoceanic Interconnections': '1hQhU5mqyRbDfZLtE9-3NAuysPGKxKpFpqqzWBtzmvfM',
                'Revolutions': '1Hs0XNGgxOTzd0NcnRFxQT9wpy0G2A5uWwF3ynHfLjpY',
                "Consequences of Industrialization": "1mIslBLg-97Ctfxp40oVsFYbbMb9caR-A6fS6s6Okpkk",
                "Global Conflict": "1WF1Nz9DTeTLfAtg_TvX6M8ZsIawQmWGX-iT7y2r5O0E",
                'Cold War and Decolonization': '1uCBmVyH5PWrrNslJjvVT66YB1dL57i9xndGwi_D2UNc',
                'Globalization': '18A6Zmfj2SJyJ7M-ibe-_GJiwtq9SjSE9fcKh8WgL8A0'
            },
            "LO_ORDER_SHEET_CONFIG": {
                'spreadsheet_id': '1PVTBLijN4n6scHsxTI0QnyPNF3JZZnhYfHQPwpQe--4',
                'sheet_name': 'Official Curriculum',
                'domain_col': 6,      # Column G
                'cluster_desc_col': 8, # Column I
                'standard_desc_col': 10,  # Column K
            },
            "EDGES_SHEET": "7. Relationship Gen Output",
            "NODES_SHEET": "Final Schema Data Model"
        },
        "AP US History": {
            "SPREADSHEET_CONFIG": {
                'Period 1: 1491-1607': '15Zsw1C8adrsbXszzaSDOlWcbrfMyh-cQ0lUaz5731RI',
                'Period 2: 1607-1754': '1D_9Kxh6ll_HYcMEVJSitk9ySqkNCeMi5q2OsVnwLvo0',
                'Period 3: 1754-1800': '1WXPE0KZq2KwBdRhTEKyKn3kzQ8_d_WSMBYnRIB_zsHw',
                'Period 4: 1800-1848': '1O7e1xS3mSnevXYMLP0VW1ZmAv-cuBT_TpJLzI-eL8m4',
                'Period 5: 1844-1877': '1Ze8rU26C9A0_s1lW0Y17ly_V2sNcVyp2LmLxoGVEuC0',
                'Period 6: 1865-1898': '1QvOBh43xJX2rZSFh9sVF2CnAhA_Qhwvp8lYX7igmgf8',
                'Period 7: 1890-1945': '1AMovm51ky0eZGQIonQGhGw-sCX_O3Nzesd_AZ6dv-D4',
                'Period 8: 1945-1980': '1tQ6NBA590PQ2Tw13ajJei0r87u7WL2BMd_PDdu-i2LU',
                'Period 9: 1980-Present': '1btaNi4f5nmHC8uoWS2raIhYlbqTDYa0J8UV_bmmJfyU'
            },
            "LO_ORDER_SHEET_CONFIG": {
                'spreadsheet_id': '1IhtIh18qnYtPqcvGX8c4hZr3RTJ-51nXe66EGPnhoEs',
                'sheet_name': 'Official Curriculum',
                'domain_col': 6,      # Column G
                'cluster_desc_col': 8, # Column I
                'standard_desc_col': 10,  # Column K
            },
            "EDGES_SHEET": "Relationship Gen Output",
            "NODES_SHEET": "Final Schema Data Model"
        }
        
    }

    # These configs remain the same regardless of subject
    NODES_SHEET_CONFIG = {
        'id_col': 0,         # Column A: Node ID
        'fact_text_col': 1,  # Column B: Node Statement
        'classification_col': 3,  # Column D: Classification
        'is_definition_col': 4,   # Column E: Definition
        'theme_col': 6,      # Column G: Theme
        'section_mapping_col': 7, # Column H: Section Mapping
        'lo_mapping_col': 8,  # Column I: LO Mapping ID
    }
    
    EDGES_SHEET_CONFIG = {
        'source_id_col': 0,    # Column A: Source Fact ID
        'source_statement_col': 1,  # Column B: Source Statement
        'target_id_col': 2,    # Column C: Target Fact ID
        'target_statement_col': 3,  # Column D: Target Statement
        'type_col': 4,         # Column E: Relationship Type
        'strength_col': 5,     # Column F: Strength
        'direction_col': 6,    # Column G: Direction
        'explanation_col': 7,  # Column H: Explanation
    }
    
    XU_PREFIX = "IU_"  # Prefix for cross-unit nodes

    def __init__(self, context: Context):
        """Initialize the config based on the subject in the context.
        
        Args:
            context: The context object containing the subject information
        """
        self.context = context
        self.subject_config = self._get_subject_config(context.subject)
        
        # Initialize Google Sheets clients
        spreadsheet_id = self.get_spreadsheet_id(context.chapter)
        self._kg_sheets_client = GoogleSheetsClient(spreadsheet_id)
        self._curriculum_sheets_client = GoogleSheetsClient(self.lo_order_sheet_config['spreadsheet_id'])

    def _get_subject_config(self, subject: str) -> Dict:
        """Get the configuration for a specific subject.
        
        Args:
            subject: The subject name to get configuration for
            
        Returns:
            Configuration dictionary for the specified subject
        """
        # Check if any key in SUBJECT_CONFIGS is a prefix of the subject
        for config_subject, config in self.SUBJECT_CONFIGS.items():
            if subject.startswith(config_subject):
                return config
        else:
            raise ValueError(f"No configuration found for subject: {subject}")
            
    
    def get_spreadsheet_id(self, chapter: str) -> str:
        """Get spreadsheet ID for given chapter.
        
        Args:
            chapter: Chapter name to get spreadsheet ID for
            
        Returns:
            Spreadsheet ID for the chapter
        """
        spreadsheet_config = self.subject_config["SPREADSHEET_CONFIG"]
        if chapter not in spreadsheet_config:
            logger.error(f"No spreadsheet configured for chapter: {chapter}")
            raise ValueError(f"Chapter {chapter} not configured")
        return spreadsheet_config[chapter]
    
    @property
    def lo_order_sheet_config(self) -> Dict:
        """Get the learning objective order sheet configuration."""
        return self.subject_config["LO_ORDER_SHEET_CONFIG"]
    
    @property
    def edges_sheet(self) -> str:
        """Get the edges sheet name."""
        return self.subject_config["EDGES_SHEET"]
    
    @property
    def nodes_sheet(self) -> str:
        """Get the nodes sheet name."""
        return self.subject_config["NODES_SHEET"]
    
    @property
    def nodes_sheet_config(self) -> Dict:
        """Get the nodes sheet configuration."""
        return self.NODES_SHEET_CONFIG
    
    @property
    def edges_sheet_config(self) -> Dict:
        """Get the edges sheet configuration."""
        return self.EDGES_SHEET_CONFIG
    
    @property
    def xu_prefix(self) -> str:
        """Get the cross-unit prefix."""
        return self.XU_PREFIX
    
    @property
    def kg_sheets_client(self) -> GoogleSheetsClient:
        """Get the Google Sheets client for the knowledge graph data."""
        return self._kg_sheets_client
    
    @property
    def curriculum_sheets_client(self) -> GoogleSheetsClient:
        """Get the Google Sheets client for the curriculum data."""
        return self._curriculum_sheets_client

class KnowledgeGraphGenerator:
    """Generates knowledge graph from Google Sheets data."""
    
    def __init__(self, config: KnowledgeGraphConfig):
        """Initialize the knowledge graph generator.
        
        Args:
            config: The configuration object for this generator
        """
        self.config = config
    
    @staticmethod
    def _strings_equal(str1: str, str2: str) -> bool:
        """Compare two strings ignoring case, whitespace, and trailing periods.
        
        Args:
            str1: First string to compare
            str2: Second string to compare
            
        Returns:
            True if strings are equal after normalization
        """
        if not str1 and not str2:
            return True
        if not str1 or not str2:
            return False
        
        # Normalize both strings: remove whitespace, convert to lowercase, remove trailing periods
        norm1 = str1.strip().lower().rstrip('.')
        norm2 = str2.strip().lower().rstrip('.')
        
        # Replace actual Unicode quotes
        quote_replacements = {
            "'": "'", "′": "'", "՚": "'", "＇": "'", "`": "'",  # Various single quotes
            '"': '"', """: '"', """: '"', "″": '"', "〞": '"', "＂": '"', "“": '"', "”": '"', # Various double quotes
        }
        
        for old, new in quote_replacements.items():
            norm1 = norm1.replace(old, new)
            norm2 = norm2.replace(old, new)
        
        # Equality check
        return norm1 == norm2

    @staticmethod
    def _string_contains(text: str, substring: str) -> bool:
        """Check if text contains substring, ignoring case, whitespace, and trailing periods.
        
        Args:
            text: Text to search in
            substring: Substring to search for
            
        Returns:
            True if normalized text contains normalized substring
        """
        if not text or not substring:
            return False
        # Normalize both strings
        norm_text = text.strip().lower().rstrip('.')
        norm_substring = substring.strip().lower().rstrip('.')
        return norm_substring in norm_text

    def generate(self, context: Context) -> LessonKnowledgeGraph:
        """Generate knowledge graph for given context."""
        logger.info("=== Starting Knowledge Graph Generation for %s ===", context.subsection)
        
        # Validate sheet data consistency
        self._validate_sheets(context)
        
        # Get nodes and edges
        current_nodes, previous_nodes = self._get_all_nodes(context)
        lo_edges, iu_edges = self._categorize_edges(context, current_nodes, previous_nodes)
        
        # Split nodes by type
        lo_nodes, xu_nodes = self._split_nodes_by_type(current_nodes)
        
        # Log summary
        self._log_generation_summary(context, previous_nodes, lo_edges, iu_edges, xu_nodes)
        
        return LessonKnowledgeGraph(
            lo_nodes=lo_nodes,
            lo_edges=lo_edges,
            iu_edges=iu_edges if iu_edges else None,
            xu_facts=xu_nodes if xu_nodes else None
        )

    def _get_all_nodes(self, context: Context) -> Tuple[Dict[str, KGNode], Dict[str, KGNode]]:
        """Get current and previous nodes for the context.
        
        Args:
            context: The context containing chapter, section, and subsection information
            
        Returns:
            Tuple of (current_nodes, previous_nodes)
        """
        # Get previous LOs in the same chapter
        previous_los = self._get_previous_los(context)
        if previous_los:
            logger.info("Found %d previous learning objectives for %s", len(previous_los), context.subsection)
        else:
            logger.info("No previous learning objectives found for %s", context.subsection)
            
        # Fetch current LO nodes
        current_nodes = self._fetch_nodes([(context.subsection, context.section)])
        
        # Fetch nodes for previous LOs
        previous_nodes = self._fetch_nodes(previous_los) if previous_los else {}
        logger.info(f"Found {len(previous_nodes)} previous nodes and {len(current_nodes)} current nodes.")
        
        return current_nodes, previous_nodes

    def _split_nodes_by_type(self, nodes: Dict[str, KGNode]) -> Tuple[List[KGNode], List[KGNode]]:
        """Split nodes into LO nodes and XU nodes based on prefix.
        
        Args:
            nodes: Dictionary of nodes to split
            
        Returns:
            Tuple of (lo_nodes, xu_nodes)
        """
        lo_nodes = []
        xu_nodes = []
        
        for node in nodes.values():
            if node.id.startswith(self.config.xu_prefix):
                xu_nodes.append(node)
            else:
                lo_nodes.append(node)
                
        return lo_nodes, xu_nodes

    def _log_generation_summary(self, context: Context, previous_nodes: Dict[str, KGNode],
                              lo_edges: List[KGEdge], iu_edges: List[KGEdge], 
                              xu_nodes: List[KGNode]) -> None:
        """Log summary of the generated knowledge graph.
        
        Args:
            context: The context containing subsection information
            previous_nodes: Dictionary of nodes from previous LOs
            lo_edges: List of LO edges
            iu_edges: List of intra-unit edges
            xu_nodes: List of cross-unit nodes
        """
        if previous_nodes:
            logger.info("Previous LO nodes: %d facts for %s", len(previous_nodes), context.subsection)
            
        logger.info("Edges - LO edges: %d, Intra-unit edges: %d for %s", 
                   len(lo_edges), len(iu_edges) if iu_edges else 0, context.subsection)
        
        if xu_nodes:
            logger.info("Cross-unit facts: %d for %s", len(xu_nodes), context.subsection)
            
        logger.info("=== Knowledge Graph Generation Complete ===")
    
    def _validate_sheets(self, context: Context) -> None:
        """Validate that all LO mappings and clusters in nodes sheet exist in LO order sheet.
        
        Args:
            context: The context containing subsection information
            
        Raises:
            ValueError: If any LO mapping or cluster in nodes sheet is not found in LO order sheet.
        """
        lo_order_config = self.config.lo_order_sheet_config
        
        # Get all LOs from LO order sheet
        lo_data = self.config.curriculum_sheets_client.read_batch_from_sheet(
            sheet_name=lo_order_config['sheet_name'],
            start_row=5,  # Skip header
            num_rows=self.config.curriculum_sheets_client.get_last_row(lo_order_config['sheet_name']) - 1
        )
        
        # Extract all valid LOs from LO order sheet
        standard_desc_col = lo_order_config['standard_desc_col']
        valid_los = {row[standard_desc_col].strip() for row in lo_data 
                    if len(row) > standard_desc_col and row[standard_desc_col]}
        
        # Get all nodes data
        nodes_data = self.config.kg_sheets_client.read_batch_from_sheet(
            sheet_name=self.config.nodes_sheet,
            start_row=2,
            num_rows=self.config.kg_sheets_client.get_last_row(self.config.nodes_sheet) - 1
        )
        
        # Extract unique LO mappings from nodes sheet
        nodes_sheet_config = self.config.nodes_sheet_config
        lo_mapping_col = nodes_sheet_config['lo_mapping_col']
        node_los = set()
        for row in nodes_data:
            if len(row) <= lo_mapping_col or not row[lo_mapping_col]:
                continue
            
            # Each row contains a single LO
            node_los.add(row[lo_mapping_col].strip())
        
        # Find any LOs in nodes sheet that don't exist in LO order sheet
        invalid_los = {lo for lo in node_los 
                      if not any(self._strings_equal(lo, valid_lo) for valid_lo in valid_los)}
        
        if invalid_los:
            error_msg = (f"Found {len(invalid_los)} LO mappings in nodes sheet that don't exist "
                        f"in LO order sheet: {sorted(invalid_los)}")
            logger.error(error_msg)
            raise ValueError(error_msg)
    
    def _get_previous_los(self, context: Context) -> List[Tuple[str, str]]:
        """Get list of LOs and their corresponding cluster descriptions that come before the current LO in the same chapter.
        
        Args:
            context: The context containing chapter, section, and subsection information
        
        Returns:
            List of tuples containing (learning_objective, cluster_description), with unique combinations
        """
        lo_order_config = self.config.lo_order_sheet_config
        
        data = self.config.curriculum_sheets_client.read_batch_from_sheet(
            sheet_name=lo_order_config['sheet_name'],
            start_row=5,  # Skip header
            num_rows=self.config.curriculum_sheets_client.get_last_row(lo_order_config['sheet_name']) - 1
        )
        
        # Find all LOs for the current chapter
        chapter_los = set()  # Set of (LO, cluster_desc) tuples for uniqueness
        found_current = False
        domain_col = lo_order_config['domain_col']
        cluster_desc_col = lo_order_config['cluster_desc_col']
        standard_desc_col = lo_order_config['standard_desc_col']
        
        for row in data:
            # Skip rows that don't have all required columns
            if len(row) <= max(domain_col, standard_desc_col, cluster_desc_col):
                continue
                
            # Skip rows with empty values in required columns
            if not row[domain_col] or not row[standard_desc_col] or not row[cluster_desc_col]:
                continue
                
            # Check if chapter matches
            if self._strings_equal(row[domain_col], context.chapter):
                lo = row[standard_desc_col].strip()
                cluster_desc = row[cluster_desc_col].strip()
                
                if self._strings_equal(lo, context.subsection):
                    found_current = True
                    break
                chapter_los.add((lo, cluster_desc))  # Using set to ensure uniqueness
        
        if not found_current:
            raise ValueError(f"Learning objective {context.subsection} not found in curriculum sheet")
            
        return list(chapter_los) if found_current else []
    
    def _categorize_edges(self, context: Context, current_nodes: Dict[str, KGNode], 
                         previous_nodes: Dict[str, KGNode]) -> Tuple[List[KGEdge], List[KGEdge]]:
        """Fetch and categorize edges into lo_edges and iu_edges.
        
        Args:
            context: The context containing subsection information
            current_nodes: Dictionary of current nodes
            previous_nodes: Dictionary of previous nodes
            
        Returns:
            Tuple of (lo_edges, iu_edges)
        """
        if self.config.kg_sheets_client.get_last_row(self.config.edges_sheet) <= 1:
            logger.warning("No edges found in spreadsheet")
            return [], []
        
        edges_data = self.config.kg_sheets_client.read_batch_from_sheet(
            sheet_name=self.config.edges_sheet,
            start_row=2,
            num_rows=self.config.kg_sheets_client.get_last_row(self.config.edges_sheet) - 1
        )
        
        if not edges_data:
            logger.warning("No edges found in spreadsheet")
            return [], []
            # raise ValueError("No edges found in the spreadsheet")
        
        lo_edges: List[KGEdge] = []
        iu_edges: List[KGEdge] = []
        
        edges_sheet_config = self.config.edges_sheet_config
        blank_edges = 0
        
        for i, row in enumerate(edges_data):
            if len(row) < edges_sheet_config['explanation_col']:
                blank_edges += 1
                continue
            source_id = row[edges_sheet_config['source_id_col']].strip()
            target_id = row[edges_sheet_config['target_id_col']].strip()
                
            edge = KGEdge(
                type=row[edges_sheet_config['type_col']],
                explanation=row[edges_sheet_config['explanation_col']],
                strength=float(row[edges_sheet_config['strength_col']]),
                direction=row[edges_sheet_config['direction_col']],
                source_id=source_id,
                target_id=target_id,
                source_statement=row[edges_sheet_config['source_statement_col']],
                target_statement=row[edges_sheet_config['target_statement_col']]
            )

           
            # Categorize edge based on node membership
            if source_id in current_nodes and target_id in current_nodes:
                lo_edges.append(edge)
            elif (source_id in current_nodes and target_id in previous_nodes) or \
                 (source_id in previous_nodes and target_id in current_nodes):
                iu_edges.append(edge)

        if blank_edges > 0:
            logger.warning(f"Skipped {blank_edges} edges due to missing columns for {context.subsection}")

        if not iu_edges:
            
            # Filter edges to only include those where source is in current nodes
            source_edges = [[row[edges_sheet_config['source_id_col']], row[edges_sheet_config['target_id_col']]] 
                           for row in edges_data if row[edges_sheet_config['source_id_col']] in current_nodes]
            target_edges = [[row[edges_sheet_config['source_id_col']], row[edges_sheet_config['target_id_col']]] 
                           for row in edges_data if row[edges_sheet_config['target_id_col']] in current_nodes]
            
            if len(source_edges) == len(target_edges) and len(source_edges) == len(lo_edges):
                logger.info(f"All edges are lesson edges for {context.subsection}")
            else:
                logger.warning(f"No iu_edges, mostly only edges with forward lessons for {context.subsection}")
                
        return lo_edges, iu_edges
    
    def _fetch_nodes(self, los_with_sections: List[Tuple[str, str]]) -> Dict[str, KGNode]:
        """Fetch and process nodes from spreadsheet.
        
        Args:
            los_with_sections: List of tuples containing (learning_objective, section) to fetch nodes for
            
        Returns:
            Dictionary of nodes
        """
        nodes_data = self.config.kg_sheets_client.read_batch_from_sheet(
            sheet_name=self.config.nodes_sheet,
            start_row=2,
            num_rows=self.config.kg_sheets_client.get_last_row(self.config.nodes_sheet) - 1
        )
        
        nodes_sheet_config = self.config.nodes_sheet_config
        nodes: Dict[str, KGNode] = {}
        for row in nodes_data:
            if len(row) <= nodes_sheet_config['lo_mapping_col']:
                continue
            node_id = row[nodes_sheet_config['id_col']].strip()
            lo_mapping = row[nodes_sheet_config['lo_mapping_col']].strip()
            section_mapping = row[nodes_sheet_config['section_mapping_col']].strip() if len(row) > nodes_sheet_config['section_mapping_col'] else ""
            
            # Check if node matches any of the LO and section combinations
            for lo, section in los_with_sections:
                if (self._strings_equal(lo_mapping, lo) and 
                    self._strings_equal(section_mapping, section)):
                    nodes[node_id] = self._create_node(row)
                    break
        
        if not nodes:
            logger.error("No nodes found for learning objectives: %s", 
                        [f'{lo} -- {section}' for lo, section in los_with_sections])
            raise ValueError(f"No nodes found for the given learning objectives")
            
        return nodes
        
    def _create_node(self, row: List[str]) -> KGNode:
        """Helper method to create a KGNode from a row of data.
        
        Args:
            row: Row of data to create a node from
            
        Returns:
            Created KGNode
        """
        nodes_sheet_config = self.config.nodes_sheet_config
        
        return KGNode(
            id=row[nodes_sheet_config['id_col']].strip(),
            fact_text=row[nodes_sheet_config['fact_text_col']].strip(),
            is_definition=str(row[nodes_sheet_config['is_definition_col']]).upper().strip() == "TRUE" 
                        if str(row[nodes_sheet_config['is_definition_col']]) else None,
            theme=row[nodes_sheet_config['theme_col']].strip(),
            classification=row[nodes_sheet_config['classification_col']].strip() 
                          if row[nodes_sheet_config['classification_col']] else None,
        )

@with_logging_context(LayerName.KNOWLEDGE_GRAPH)
@exception_handler
def generate_lesson_knowledge_graph(output_path: str, output_type: str, inputs: Dict[str, Any]) -> Dict[str, Any]:
    """Generate knowledge graph for a lesson.
    
    Args:
        output_path: Path to output the knowledge graph to
        output_type: Type of output to generate
        inputs: Dictionary of inputs containing context information
        
    Returns:
        Dictionary containing the generated knowledge graph
    """
    context = Context(**inputs)
    
    # Create configuration based on context
    # The config now handles creation of Google Sheets clients
    config = KnowledgeGraphConfig(context)
    
    # Create generator with configuration
    # No need to pass sheets clients separately
    generator = KnowledgeGraphGenerator(config)
    
    # Generate knowledge graph
    knowledge_graph = generator.generate(context)
    return knowledge_graph.model_dump()

if __name__ == '__main__':
    from config.courses import get_execution_input
    setup_logging(level=logging.DEBUG)
    exec_input    = get_execution_input(
        subject = "AP World History - v6", 
        subsection = "Explain the systems of government employed by Chinese dynasties and how they developed over time."
    )
    context = Context(**prep_content_gen_input(exec_input))
    print(context.key)
    print_json(generate_lesson_knowledge_graph('', '', context.model_dump()))
