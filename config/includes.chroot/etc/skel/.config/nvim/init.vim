" Vim-plug plugin manager will be installed on first Vim launch
" NeurOS Neovim configuration — optimized for development with local LLM

" === Basic Settings ===
set number
set relativenumber
set mouse=a
set clipboard=unnamedplus
set encoding=utf-8
set tabstop=4
set shiftwidth=4
set expandtab
set smartindent
set autoindent
set cursorline
set termguicolors
set splitbelow
set splitright
set hidden
set updatetime=300
set signcolumn=yes

" === Plugin Manager (vim-plug) ===
call plug#begin('~/.config/nvim/plugged')

" UI
Plug 'morhetz/gruvbox'
Plug 'vim-airline/vim-airline'
Plug 'preservim/nerdtree'

" Dev tools
Plug 'tpope/vim-fugitive'
Plug 'airblade/vim-gitgutter'
Plug 'junegunn/fzf', { 'do': { -> fzf#install() } }
Plug 'junegunn/fzf.vim'

" LSP
Plug 'neovim/nvim-lspconfig'
Plug 'hrsh7th/nvim-cmp'
Plug 'hrsh7th/cmp-nvim-lsp'
Plug 'hrsh7th/cmp-buffer'
Plug 'hrsh7th/cmp-path'

" LLM Integration — ollama.nvim
Plug 'nomnivore/ollama.nvim'

call plug#end()

" === Theme ===
colorscheme gruvbox
set background=dark

" === Keymaps ===
let mapleader = " "

" NERDTree
nnoremap <leader>n :NERDTreeToggle<CR>
nnoremap <leader>f :NERDTreeFind<CR>

" fzf
nnoremap <leader>p :Files<CR>
nnoremap <leader>g :Rg<CR>
nnoremap <leader>b :Buffers<CR>

" LSP
nnoremap <leader>gd :lua vim.lsp.buf.definition()<CR>
nnoremap <leader>gr :lua vim.lsp.buf.references()<CR>
nnoremap <leader>rn :lua vim.lsp.buf.rename()<CR>
nnoremap K :lua vim.lsp.buf.hover()<CR>

" === LSP Config ===
lua << EOF
local lspconfig = require('lspconfig')
local cmp = require('cmp')

-- nvim-cmp setup
cmp.setup({
  mapping = cmp.mapping.preset.insert({
    ['<C-b>'] = cmp.mapping.scroll_docs(-4),
    ['<C-f>'] = cmp.mapping.scroll_docs(4),
    ['<C-Space>'] = cmp.mapping.complete(),
    ['<C-e>'] = cmp.mapping.abort(),
    ['<CR>'] = cmp.mapping.confirm({ select = true }),
  }),
  sources = cmp.config.sources({
    { name = 'nvim_lsp' },
    { name = 'buffer' },
    { name = 'path' },
  })
})

-- Ollama LSP (if available)
-- Use ollama.nvim for AI completion
EOF

" === Ollama.nvim Config ===
" Defer setup until plugin is loaded
lua << EOF
vim.schedule(function()
  local ok, ollama = pcall(require, 'ollama')
  if ok then
    ollama.setup({
      model = "mistral",
      url = "http://localhost:11434",
    })
  end
end)
EOF

" === Airline ===
let g:airline_theme = 'gruvbox'
let g:airline_powerline_fonts = 1
